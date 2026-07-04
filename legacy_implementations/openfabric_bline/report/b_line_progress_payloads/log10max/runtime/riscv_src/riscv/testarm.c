#include "DpuAPI.h"
#include <stdio.h>
#include "../csv_generate/conf.h"

static void wait_dma(int flag)
{
    while (!DPU_DMATransferFinish(flag));
}

static void dma_transfer_simple(unsigned ddr_addr, unsigned spm_addr, unsigned byte_size, unsigned trans_direc)
{
    DPU_SpmTransfer((void*)ddr_addr, 0, (void*)spm_addr, 0,
                    byte_size, 1, byte_size, trans_direc, 0, 0);
    wait_dma(0);
}

int main(void)
{
    printf("openfabric generated riscv control: log10max_single_task\n");
    DPU_CbufTransfer((void*)CBUF_DDR_ADDR);
    wait_dma(2);
    DPU_MiccTransfer((void*)MICC_DDR_ADDR);
    wait_dma(0);

    /* before_launch DMA transfers */
    dma_transfer_simple((unsigned)(SPM_DDR_ADDR + 0x0), (unsigned)0x0, (unsigned)0x20000, (unsigned)2);

    DPU_Kernel_Start(1, 1, (void*)0, 0, 0, 0);
    while (!DPU_Kernel_Wait_Finish(0));

    /* after_launch DMA transfers */
    dma_transfer_simple((unsigned)(SPM_RST_DDR_ADDR + 0x80000), (unsigned)0x80000, (unsigned)0x20000, (unsigned)0);
    DPU_App_Finish();
    printf("openfabric generated riscv control done\n");
    return 0;
}
