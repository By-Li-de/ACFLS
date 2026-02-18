# ACFLS
Logic Synthesizer Project for ACF.

TODO:
- Create/find a suitable testproject. Ideally a simple RISC-V CPU in in Verilog for the final tests. In the beginning we will use a much smaller example, maybe a 4-bit counter, to see if our stuff works.

- Parser: reads the verilog and creates abstract syntax tree (AST), Ideally we use a tool here like PyVerilog. Otherwise this will be a LOT of work.

- Elaboration and Hierarchy flattening: traverses AST to resolve parameters, unroll loops and instantiate modules.

- Bit-Blasting / Macro generation: Convert A + B into explicit XOR/AND/OR gate structures, if ... into MUX logic

- Sequential Inference: Detect patterns (always @(posedge clk) and instantiate D-Flip-Flop primitive in the netlist)

- Logic Optimization (ambitious but optional)

- Export: writes a netlist into a standard format.

- get a reference netlist for comparison

We do Verilog, because it's easier than VHDL. 
Ideally the CPU testproject is limited and unoptimized, leaving out more complex types or features of Verilog. 
A minimum functional subset should be something like:
combinatorial logic, "assign" statements, logical operators(&,|,^,!) and arithmetic(+,-)

Sequential Logic: "always @(posedge clk)blocks, Flip Flops

Control Flow: "if-else", "case" (maps to MUXes)

Modules: module instatiation and port mapping.

ideally we can do without structs, enums, generate blocks, initial blocks, delays and tristates and so on.

I will also ask if we need to make the lexer/parser ourselves or if we can use an existing tool for that.
In terms of language, we can use any language. I would prefer Python but it will depend on the code available as reference online. 

The Program should work as follows:

launch the main file while specifying an input file like "Pyothon LogSyn Test1" or something like that
The main should then call the parser and parse the test file, generating and Abstract Syntax Tree, which it should save as a seperate file like "Test1_AST" 

then the main file calls the Elaboration function, which does it's thing and generates another output intermediate file "Test1_elab" or something.

We go through each step and generate a new file each time, until we have made the final step and we get a final netlist file.


Final segmentation of the porject:

1. Main file, reads input file and orchestrates calls for other modules. (main.py)

2. Parsing, Inputs .v source file, Wraps PyVerilog to generate AST (stage_parser.py)

3. High level elaboration, input AST, flattens hierarchy (resolves includes and module initiations), Sequential inference(identifies "always @(posedge) blocks and marks signals as D-flip-flops), resolves parameters (like WIDTH=32), outputs high-level netlist (stage_elaboration.py)

4. Bit blasting, input high-level netlist, expands signals into individual wire objects, replaces operators with gates (+,-,== to adders, XORs etc.), replaces if/else with MUX structures, outputs list of primitives (stage_bitblast.py)

5. Export: input list of primitives / gate level netlist, translates into target output format(BLIF).(stage_export.py)

6. Define Python classes necessary for the netlist(netlist.py)

RISC-V CORE CODE FILES HANDLED:
ALUControl.v :  O
Control.v:      X
Mem_Model.v:    X
REG_FILE.v:     X
RISCV_CLKRST.v: X
RISCV_TOP.v:    X

ATTENTION: MAKE SURE TO INSTALL PYVERILOG WITH "pip install pyverilog" BEFORE RUNNING
If you encounter WinError2: install iverilog and during installation check "Add to PATH" box. 

LIMITATIONS: Our project does NOT handle multiple file inputs, each verilog file MUST be synthesized individually to ensure correctness.
We do not check for dependencies or logic errors, we assume the verilog code to be correct. The goal is not to create a functioning Linter.(The parser may catch syntax errors.)

Credit: RISC-V CPU code: https://github.com/hushon/Tiny-RISCV-CPU/tree/master