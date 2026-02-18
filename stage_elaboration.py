# stage_elaboration.py
# High-level elaboration: build a high-level netlist (Module/Signal/Gate)
# from the PyVerilog AST.
# Supports:
# - Ports (input/output)
# - Sequential Logic: always @(posedge clk)
# - Combinational Logic: always @(*) with nested if-else (MUX inference)
# - Operators: +, ==, &&, ||

import os
import re
from netlist import Module, Signal, Gate

from pyverilog.vparser.ast import (
    Source, Description, ModuleDef,
    Ioport, Input, Output, Wire, Reg,
    Width, IntConst, Identifier,
    Always, SensList, Sens, Block,
    IfStatement, NonblockingSubstitution, BlockingSubstitution,
    Plus, Eq, Land, Lor
)

# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _parse_const_value(val_str):
    """
    Parses Verilog constants like "4'b1010", "32'd100", or "5'bxxxxx"
    """
    if "'" in val_str:
        width_part, val_part = val_str.split("'")
        base = val_part[0].lower() # 'b', 'h', 'd'
        number = val_part[1:]
        
        # Handle "don't cares" (x) by treating them as 0 for now
        number = number.replace('x', '0').replace('z', '0')
        
        try:
            if base == 'b':
                return int(number, 2)
            elif base == 'h':
                return int(number, 16)
            elif base == 'd':
                return int(number)
        except ValueError:
            return 0
    return int(val_str)

def _parse_width(node):
    """Return bit-width as int. If no width, return 1."""
    if node is None:
        return 1
    if isinstance(node, Width):
        msb = int(node.msb.value, 0)
        lsb = int(node.lsb.value, 0)
        return abs(msb - lsb) + 1
    return 1

def _get_or_create_signal(mod: Module, name: str, width=1, **attrs):
    """Fetch existing signal or create a new one."""
    s = mod.get_signal(name)
    if s is None:
        s = Signal(name=name, width=width, **attrs)
        mod.add_signal(s)
    else:
        # Update width if we learned it's larger
        if s.width == 1 and width != 1:
            s.width = width
        # Merge attributes
        s.is_input = s.is_input or attrs.get("is_input", False)
        s.is_output = s.is_output or attrs.get("is_output", False)
        s.is_reg = s.is_reg or attrs.get("is_reg", False)
    return s

def _intconst_decl_width(value: str):
    """Parse Verilog sized constant like: 4'b0 -> returns 4."""
    m = re.match(r"^\s*(\d+)\s*'[bBdDhHoO].*$", value)
    return int(m.group(1)) if m else None

# -------------------------------------------------------------------------
# Expression Parsing (Recursion)
# -------------------------------------------------------------------------

def _expr_to_signal_and_gates(mod: Module, expr, expected_width=None):
    """
    Converts an AST expression (A+B, A==B) into Signals and Gates.
    Returns: (output_signal, list_of_new_gates)
    """
    extra_gates = []

    # 1. Identifier (Variables)
    if isinstance(expr, Identifier):
        s = _get_or_create_signal(mod, expr.name)
        # Propagate expected width backwards if signal is generic
        if expected_width is not None and s.width == 1 and expected_width != 1:
            s.width = expected_width
        return s, extra_gates

    # 2. Integer Constants
    if isinstance(expr, IntConst):
        val = _parse_const_value(expr.value)
        declared_w = _intconst_decl_width(expr.value)
        w = declared_w or expected_width or 32 # Default to 32 if unknown
        
        const_name = f"CONST_{val}_{w}b_{id(expr)}"
        s = _get_or_create_signal(mod, const_name, width=w)
        return s, extra_gates

    # 3. Binary Operators
    op_map = {
        Plus: "ADD",
        Eq:   "EQ",
        Land: "AND",
        Lor:  "OR"
    }
    
    expr_type = type(expr)
    if expr_type in op_map:
        op_name = op_map[expr_type]
        
        # Recurse Left/Right
        # For Logic/Comparison (EQ, AND, OR), operands don't need to match output width (output is 1)
        # For Arithmetic (ADD), they usually do.
        req_w = expected_width if op_name == "ADD" else None
        
        a_sig, a_g = _expr_to_signal_and_gates(mod, expr.left, expected_width=req_w)
        b_sig, b_g = _expr_to_signal_and_gates(mod, expr.right, expected_width=req_w)
        extra_gates.extend(a_g)
        extra_gates.extend(b_g)

        # Determine Output Width
        if op_name in ["EQ", "AND", "OR"]:
            out_w = 1
        else:
            out_w = expected_width or max(a_sig.width, b_sig.width)

        tmp_name = f"tmp_{op_name}_{len(mod.gates)}"
        tmp = _get_or_create_signal(mod, tmp_name, width=out_w)

        extra_gates.append(Gate(op_name, [a_sig, b_sig], tmp))
        return tmp, extra_gates

    raise NotImplementedError(f"Expression not supported yet: {type(expr).__name__}")

# -------------------------------------------------------------------------
# MUX Tree Building (For nested if-else)
# -------------------------------------------------------------------------

def _build_mux_tree(mod, stmt, target_name):
    """
    Recursively converts a statement (Block, If, or Assignment) into a Signal.
    Used for Combinational Logic (always @*).
    Returns: (result_signal, list_of_gates)
    """
    gates = []

    # Case A: Block (begin ... end) -> just recurse on the content
    if isinstance(stmt, Block):
        # We assume the block ends with the relevant assignment or logic
        # For ALUControl, usually just one statement inside or a chain
        if not stmt.statements:
            return None, []
        # In a real compiler we'd handle multiple statements. 
        # For this MVP, we assume the block wraps the logic flow.
        return _build_mux_tree(mod, stmt.statements[0], target_name)

    # Case B: Assignment (Base Case)
    # Handles: ALU_operation = ...
    if isinstance(stmt, BlockingSubstitution) or isinstance(stmt, NonblockingSubstitution):
        if stmt.left.var.name != target_name:
            # This assignment is for a different variable, ignore in this tree pass
            # (In a full synth, we'd need to handle multiple targets)
            return None, []
        
        # Convert RHS to signal
        target_sig = mod.get_signal(target_name)
        rhs_sig, g = _expr_to_signal_and_gates(mod, stmt.right.var, expected_width=target_sig.width)
        return rhs_sig, g

    # Case C: If Statement (Recursive MUX)
    if isinstance(stmt, IfStatement):
        # 1. Condition
        cond_sig, cond_gates = _expr_to_signal_and_gates(mod, stmt.cond)
        gates.extend(cond_gates)

        # 2. True Branch
        true_sig, true_gates = _build_mux_tree(mod, stmt.true_statement, target_name)
        gates.extend(true_gates)

        # 3. False Branch
        if stmt.false_statement:
            false_sig, false_gates = _build_mux_tree(mod, stmt.false_statement, target_name)
            gates.extend(false_gates)
        else:
            # Implicit else: keep previous value (latch inference) 
            # or default 0 for pure combinational?
            # For ALUControl, we assume full coverage or latch.
            # Let's default to the target signal itself (latch behavior) or 0.
            # Ideally, we should create a 'Latch' warning.
            false_sig = mod.get_signal(target_name) 

        if true_sig is None or false_sig is None:
            return None, []

        # 4. Create MUX
        mux_out_name = f"mux_{target_name}_{len(mod.gates)}"
        mux_out = _get_or_create_signal(mod, mux_out_name, width=true_sig.width)
        
        # Gates convention: MUX [Select, True_Input, False_Input] -> Output
        gates.append(Gate("MUX", [cond_sig, true_sig, false_sig], mux_out))
        
        return mux_out, gates

    return None, []

# -------------------------------------------------------------------------
# Main Run Loop
# -------------------------------------------------------------------------

def run(ast):
    if not isinstance(ast, Source):
        raise TypeError("Expected PyVerilog Source node as AST root.")
    
    desc = ast.description
    top = next((d for d in desc.definitions if isinstance(d, ModuleDef)), None)
    if not top: raise ValueError("No ModuleDef found.")

    mod = Module(top.name)

    # 1. Parse Ports
    for p in top.portlist.ports:
        if isinstance(p, Ioport):
            first, second = p.first, p.second
            width = _parse_width(first.width)
            if isinstance(first, Input):
                _get_or_create_signal(mod, first.name, width=width, is_input=True)
            elif isinstance(first, Output):
                is_reg = isinstance(second, Reg)
                _get_or_create_signal(mod, first.name, width=width, is_output=True, is_reg=is_reg)

    # 2. Parse Items (Always Blocks)
    for item in top.items:
        if isinstance(item, Always):
            # Check sensitivity list to distinguish Sequential vs Combinational
            is_clocked = False
            senslist = item.sens_list
            if isinstance(senslist, SensList):
                for s in senslist.list:
                    if s.type == "posedge":
                        is_clocked = True
            
            if is_clocked:
                # --- SEQUENTIAL LOGIC (Counter style) ---
                # (Existing logic for posedge clk)
                clk_name = senslist.list[0].sig.name
                clk_sig = _get_or_create_signal(mod, clk_name, is_input=True)
                
                # Assume if(rst)... pattern for MVP
                body = item.statement
                if isinstance(body, Block): body = body.statements[0]
                
                if isinstance(body, IfStatement):
                    # Handle Reset
                    rst_name = body.cond.name
                    rst_sig = _get_or_create_signal(mod, rst_name)
                    
                    # Target Register
                    then_stmt = body.true_statement
                    if isinstance(then_stmt, Block): then_stmt = then_stmt.statements[0]
                    target_name = then_stmt.left.var.name
                    target_sig = _get_or_create_signal(mod, target_name)
                    
                    # Reset Value
                    rst_val_sig, g_rst = _expr_to_signal_and_gates(mod, then_stmt.right.var, target_sig.width)
                    for g in g_rst: mod.add_gate(g)

                    # Enable / Else
                    else_stmt = body.false_statement
                    if isinstance(else_stmt, IfStatement):
                        en_name = else_stmt.cond.name
                        en_sig = _get_or_create_signal(mod, en_name)
                        
                        en_then = else_stmt.true_statement
                        if isinstance(en_then, Block): en_then = en_then.statements[0]
                        
                        next_val_sig, g_next = _expr_to_signal_and_gates(mod, en_then.right.var, target_sig.width)
                        for g in g_next: mod.add_gate(g)

                        # Create DFF Primitive
                        mod.add_gate(Gate("DFF_EN_RST", 
                            [next_val_sig, target_sig, en_sig, rst_val_sig, rst_sig, clk_sig], 
                            target_sig))

            else:
                # --- COMBINATIONAL LOGIC (ALU Control style) ---
                # This handles always @(*) or always @(a, b)
                # We identify the target variable by looking at the first assignment
                # (MVP Limitation: assumes always block drives one main variable)
                
                # 1. Find the target name (hacky peek)
                # We need to traverse deep to find the LHS of an assignment
                # For now, let's just process the whole tree and hope it returns a signal
                # corresponding to the output port.
                
                # In ALUControl, the target is "ALU_operation"
                # We can try to infer it, or iterate over all outputs to see which one is driven.
                # Let's try to build the tree for 'ALU_operation' specifically if it exists.
                
                target_candidates = [s.name for s in mod.signals.values() if s.is_output or s.is_reg]
                
                for target_name in target_candidates:
                    # Try to build a mux tree for this target
                    final_sig, gates = _build_mux_tree(mod, item.statement, target_name)
                    
                    if final_sig:
                        # Success! We found logic driving this signal.
                        # Add the gates
                        for g in gates: mod.add_gate(g)
                        
                        # Connect the final MUX output to the actual wire
                        # effectively: assign target_name = final_sig
                        # We use a buffer or just rename (for MVP, buffer)
                        mod.add_gate(Gate("BUF", [final_sig], mod.get_signal(target_name)))

    mod.save_json("debug_02_elab.json")
    return mod