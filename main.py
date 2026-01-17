import sys
import os
import argparse

# Import the stages (We will create these files next)
# using try-except blocks so main.py runs even if stages are missing during dev
try:
    import stage_parser
except ImportError:
    stage_parser = None

try:
    import stage_elaboration
except ImportError:
    stage_elaboration = None

try:
    import stage_bitblast
except ImportError:
    stage_bitblast = None

try:
    import stage_export
except ImportError:
    stage_export = None

def main():
    # 1. Setup Argument Parser
    parser = argparse.ArgumentParser(description="Python Logic Synthesizer (PyLogSyn)")
    parser.add_argument("input_file", help="Path to the Verilog input file (.v)")
    parser.add_argument("--output", "-o", default="out.blif", help="Path to the output BLIF file")
    
    args = parser.parse_args()
    
    input_path = args.input_file
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        sys.exit(1)

    print(f"=== Starting Synthesis for {input_path} ===")

    # ---------------------------------------------------------
    # Step 1: Parsing
    # ---------------------------------------------------------
    if stage_parser:
        print("\n[Step 1] Parsing Verilog...")
        # Returns the PyVerilog AST
        ast = stage_parser.run(input_path)
    else:
        print("Error: stage_parser module not found.")
        sys.exit(1)

    # ---------------------------------------------------------
    # Step 2: Elaboration & High-Level Synthesis
    # ---------------------------------------------------------
    if stage_elaboration:
        print("\n[Step 2] Elaboration & Inference...")
        # Takes AST, returns a Module object (from netlist.py)
        # We pass the filename to help with debug naming
        my_module = stage_elaboration.run(ast)
    else:
        print("Warning: stage_elaboration not implemented yet. Stopping.")
        sys.exit(0)

    # ---------------------------------------------------------
    # Step 3: Bit Blasting
    # ---------------------------------------------------------
    if stage_bitblast:
        print("\n[Step 3] Bit Blasting...")
        # Takes the high-level Module, modifies it in-place to be gate-level
        stage_bitblast.run(my_module)
    else:
        print("Warning: stage_bitblast not implemented yet. Stopping.")
        sys.exit(0)

    # ---------------------------------------------------------
    # Step 4: Export
    # ---------------------------------------------------------
    if stage_export:
        print(f"\n[Step 4] Exporting to {args.output}...")
        stage_export.run(my_module, args.output)
    else:
        print("Warning: stage_export not implemented yet. Stopping.")
        sys.exit(0)

    print("\n=== Synthesis Complete ===")

if __name__ == "__main__":
    main()