# netlist.py
import json

class Signal:
    """
    Represents a wire or register in the design.
    """
    def __init__(self, name, width=1, is_input=False, is_output=False, is_reg=False):
        self.name = name
        self.width = width
        self.is_input = is_input
        self.is_output = is_output
        self.is_reg = is_reg
        self.id = id(self)  # Unique ID for hashing/graphing

    def __repr__(self):
        # Easier debugging representation
        direction = "IN" if self.is_input else ("OUT" if self.is_output else "WIRE")
        kind = "REG" if self.is_reg else "NET"
        return f"<{self.name} [{self.width}] {direction} {kind}>"

    def to_dict(self):
        """Serialization for JSON export"""
        return {
            "name": self.name,
            "width": self.width,
            "attributes": {
                "input": self.is_input,
                "output": self.is_output,
                "reg": self.is_reg
            }
        }

class Gate:
    """
    Represents a logic operation.
    Before Bit-Blasting, this can be high-level (e.g., OP="ADD").
    After Bit-Blasting, this is strictly low-level (e.g., OP="AND", OP="DFF").
    """
    def __init__(self, op_type, inputs, output):
        self.op_type = op_type   # e.g., "AND", "OR", "NOT", "ADD", "MUX", "DFF"
        self.inputs = inputs     # List of Signal objects
        self.output = output     # Single Signal object driven by this gate

    def __repr__(self):
        input_names = [s.name for s in self.inputs]
        return f"[{self.op_type}] {input_names} -> {self.output.name}"

    def to_dict(self):
        """Serialization for JSON export"""
        return {
            "type": self.op_type,
            "inputs": [s.name for s in self.inputs],
            "output": self.output.name
        }

class Module:
    """
    The container for the entire design.
    """
    def __init__(self, name):
        self.name = name
        self.signals = {}  # Dict mapping name -> Signal object
        self.gates = []    # List of Gate objects

    def add_signal(self, signal):
        self.signals[signal.name] = signal

    def get_signal(self, name):
        return self.signals.get(name)

    def add_gate(self, gate):
        self.gates.append(gate)

    def to_json(self):
        """Dumps the entire netlist to a JSON-compatible dictionary"""
        return {
            "module_name": self.name,
            "signals": [s.to_dict() for s in self.signals.values()],
            "gates": [g.to_dict() for g in self.gates]
        }

    def save_json(self, filename):
        with open(filename, 'w') as f:
            json.dump(self.to_json(), f, indent=4)
        print(f"Saved intermediate netlist to {filename}")