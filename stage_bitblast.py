# stage_bitblast.py
# Bit-blasting: convert high-level gates (ADD, EQ, MUX, AND/OR) into 1-bit primitives.
# Supports:
# - Expand buses into bit signals: <name>_<i> (LSB=0)
# - ADD -> ripple-carry
# - EQ -> XNOR tree + AND reduction
# - MUX (wide) -> Array of 1-bit MUXes
# - Bitwise Ops -> Array of 1-bit gates

import re
from netlist import Signal, Gate

# ---------- helpers: naming ----------
def bit_name(base: str, i: int) -> str:
    return f"{base}_{i}"

def tmp_name(prefix: str, idx: int) -> str:
    return f"tmp_{prefix}_{idx}"

# ---------- helpers: const parsing ----------
_const_re = re.compile(r"^\s*(\d+)\s*'([bBdDhHoO])\s*([0-9a-fA-FxXzZ_]+)\s*$")

def parse_verilog_const(value: str, width_hint: int = 1) -> list[int]:
    value = value.strip()
    m = _const_re.match(value)
    if m:
        w = int(m.group(1))
        base = m.group(2).lower()
        digits = m.group(3).replace("_", "")
        digits_clean = re.sub(r"[xXzZ]", "0", digits)

        if base == "b":
            bits_str = digits_clean.zfill(w)
            bits = [1 if c == "1" else 0 for c in bits_str[::-1]]
            return bits[:w]
        elif base == "d":
            v = int(digits_clean, 10)
        elif base == "h":
            v = int(digits_clean, 16)
        elif base == "o":
            v = int(digits_clean, 8)
        else:
            v = 0
        bits = [(v >> i) & 1 for i in range(w)]
        return bits

    try:
        v = int(value, 0)
    except Exception:
        v = 0
    w = max(1, width_hint)
    return [(v >> i) & 1 for i in range(w)]


def run(mod):
    # 0) Ensure global CONST0/CONST1 exist
    const0 = mod.get_signal("CONST0")
    if const0 is None:
        const0 = Signal("CONST0", width=1)
        mod.add_signal(const0)

    const1 = mod.get_signal("CONST1")
    if const1 is None:
        const1 = Signal("CONST1", width=1)
        mod.add_signal(const1)

    # 1) Build bit-signal mapping
    bits_map = {} 

    def get_bits(sig: Signal) -> list[Signal]:
        if sig.width == 1:
            bits_map[sig.name] = [sig]
            return [sig]
        if sig.name in bits_map:
            return bits_map[sig.name]
        blist = []
        for i in range(sig.width):
            bn = bit_name(sig.name, i)
            b = mod.get_signal(bn)
            if b is None:
                b = Signal(bn, width=1, is_input=sig.is_input, is_output=sig.is_output, is_reg=sig.is_reg)
                mod.add_signal(b)
            blist.append(b)
        bits_map[sig.name] = blist
        return blist

    # Pre-create bit signals
    for s in list(mod.signals.values()):
        get_bits(s)

    def const_bits_from_signal(sig: Signal, width_hint: int) -> list[Signal]:
        if not sig.name.startswith("CONST_"):
            return get_bits(sig)
        raw = sig.name.split('_', 1)[1] # remove "CONST_"
        # Hack to handle CONST_123_32b_ID format from elaboration
        # We just try to parse the numeric part or rely on parse_verilog_const robustness
        # Simpler: If it contains 'b/d/h', parse it. If not, assume raw int.
        # But elaboration might append _ID. Let's rely on the value stored in sig object if possible?
        # Since we didn't store value in Signal in this file's version, we parse name.
        # Clean up name: "CONST_7'b0110_id123" -> try to extract 7'b0110
        # For now, simplistic approach:
        bits = parse_verilog_const(raw.split('_')[0], width_hint=width_hint)
        out = []
        for b in bits:
            out.append(const1 if b == 1 else const0)
        return out

    def get_operand_bits(sig, width):
        """Helper to get bits, handling Constants and Padding automatically."""
        if sig.name.startswith("CONST_"):
            bits = const_bits_from_signal(sig, width_hint=width)
        else:
            bits = get_bits(sig)
        
        # Pad with 0s if too short
        if len(bits) < width:
            bits = bits + [const0] * (width - len(bits))
        return bits[:width]

    # 2) Rewrite/bitblast gates
    new_gates = []
    tmp_idx = 0

    def new_tmp(prefix="t"):
        nonlocal tmp_idx
        name = tmp_name(prefix, tmp_idx)
        tmp_idx += 1
        s = mod.get_signal(name)
        if s is None:
            s = Signal(name=name, width=1)
            mod.add_signal(s)
        return s

    # 1-bit Primitive Constructors
    def XOR2(a, b, out): new_gates.append(Gate("XOR", [a, b], out))
    def AND2(a, b, out): new_gates.append(Gate("AND", [a, b], out))
    def OR2(a, b, out):  new_gates.append(Gate("OR",  [a, b], out))
    def NOT1(a, out):    new_gates.append(Gate("NOT", [a], out))
    # MUX Convention: [Select, True_Input(1), False_Input(0)]
    def MUX2(sel, d1, d0, out): new_gates.append(Gate("MUX", [sel, d1, d0], out))
    def DFF(d, clk, q):  new_gates.append(Gate("DFF", [d, clk], q))

    for g in mod.gates:
        op = g.op_type
        
        # -------- BITWISE OPS (AND, OR, XOR) --------
        if op in ["AND", "OR", "XOR"]:
            # Handles both logical (&&) and bitwise (&) if width=1
            # Handles bitwise (&, |, ^) for buses
            a, b = g.inputs
            out = g.output
            w = out.width
            
            a_bits = get_operand_bits(a, w)
            b_bits = get_operand_bits(b, w)
            out_bits = get_bits(out)
            
            constructor = XOR2 if op == "XOR" else (AND2 if op == "AND" else OR2)
            
            for i in range(w):
                constructor(a_bits[i], b_bits[i], out_bits[i])
            continue

        # -------- EQUALITY (==) --------
        if op == "EQ":
            a, b = g.inputs
            out = g.output # 1 bit output
            
            # Width is max of inputs
            w = max(a.width, b.width)
            a_bits = get_operand_bits(a, w)
            b_bits = get_operand_bits(b, w)
            
            # Logic: (A0 XNOR B0) & (A1 XNOR B1) ...
            
            eq_bits = []
            for i in range(w):
                # XNOR = NOT(XOR)
                t_xor = new_tmp("xor_eq")
                t_xnor = new_tmp("xnor_eq")
                XOR2(a_bits[i], b_bits[i], t_xor)
                NOT1(t_xor, t_xnor)
                eq_bits.append(t_xnor)
            
            # Reduce AND
            if not eq_bits:
                # Empty comparison? True
                # Connect out to 1 (Buffer)
                AND2(const1, const1, get_bits(out)[0]) 
            elif len(eq_bits) == 1:
                # Buffer the single result to output
                # Using AND with 1 as buffer
                AND2(eq_bits[0], const1, get_bits(out)[0])
            else:
                curr = eq_bits[0]
                for i in range(1, len(eq_bits)):
                    next_tmp = new_tmp("and_red")
                    AND2(curr, eq_bits[i], next_tmp)
                    curr = next_tmp
                # Connect final result
                AND2(curr, const1, get_bits(out)[0])
            continue

        # -------- MULTIPLEXER (MUX) --------
        if op == "MUX":
            # High-level inputs: [Select, True_In, False_In]
            sel, t_in, f_in = g.inputs
            out = g.output
            w = out.width
            
            sel_bit = get_bits(sel)[0] # Select is always 1 bit
            
            t_bits = get_operand_bits(t_in, w)
            f_bits = get_operand_bits(f_in, w)
            out_bits = get_bits(out)
            
            for i in range(w):
                # stage_elaboration convention: MUX(cond, true, false)
                # stage_bitblast helper convention: MUX2(sel, d1, d0, out)
                MUX2(sel_bit, t_bits[i], f_bits[i], out_bits[i])
            continue

        # -------- ADD (Ripple Carry) --------
        if op == "ADD":
            a, b = g.inputs
            out = g.output
            w = out.width
            
            a_bits = get_operand_bits(a, w)
            b_bits = get_operand_bits(b, w)
            out_bits = get_bits(out)

            carry = const0
            for i in range(w):
                # sum = a ^ b ^ carry
                t1 = new_tmp("xor")
                XOR2(a_bits[i], b_bits[i], t1)
                
                sbit = out_bits[i]
                XOR2(t1, carry, sbit)

                # carry_out logic
                t_ab = new_tmp("and")
                t_ac = new_tmp("and")
                t_bc = new_tmp("and")
                AND2(a_bits[i], b_bits[i], t_ab)
                AND2(a_bits[i], carry, t_ac)
                AND2(b_bits[i], carry, t_bc)

                t_or1 = new_tmp("or")
                OR2(t_ab, t_ac, t_or1)
                cnext = new_tmp("or")
                OR2(t_or1, t_bc, cnext)
                carry = cnext
            continue

        # -------- DFF_EN_RST (Macro) --------
        if op == "DFF_EN_RST":
            # [D_when_enable, Q_old, enable, D_reset, reset, clk]
            d_en, q_old, en, d_rst, rst, clk = g.inputs
            q = g.output
            w = q.width
            
            d_en_bits = get_operand_bits(d_en, w)
            d_rst_bits = get_operand_bits(d_rst, w)
            q_old_bits = get_operand_bits(q_old, w)
            q_bits = get_bits(q)
            
            en_b = get_bits(en)[0]
            rst_b = get_bits(rst)[0]
            clk_b = get_bits(clk)[0]

            for i in range(w):
                # mux_en = en ? d_en : q_old
                mux_en = new_tmp("mux")
                MUX2(en_b, d_en_bits[i], q_old_bits[i], mux_en)

                # mux_rst = rst ? d_rst : mux_en
                mux_rst = new_tmp("mux")
                MUX2(rst_b, d_rst_bits[i], mux_en, mux_rst)

                DFF(mux_rst, clk_b, q_bits[i])
            continue
        
        # -------- Passthrough for existing primitives --------
        if op in ["NOT", "BUF"]:
            # Basic 1-bit gate handling
            inp = g.inputs[0]
            out = g.output
            if op == "NOT":
                NOT1(get_bits(inp)[0], get_bits(out)[0])
            elif op == "BUF":
                # Using AND with 1 as buffer
                AND2(get_bits(inp)[0], const1, get_bits(out)[0])
            continue

        raise NotImplementedError(f"Bitblast: unsupported gate type {op}")

    mod.gates = new_gates
    mod.save_json("debug_03_bitblast.json")