module counter (
    input wire clk,
    input wire rst,
    input wire enable,
    output reg [3:0] count
);

    // Synchronous logic with reset and enable
    always @(posedge clk) begin
        if (rst) begin
            count <= 4'b0;
        end else if (enable) begin
            count <= count + 1;
        end
    end
endmodule
