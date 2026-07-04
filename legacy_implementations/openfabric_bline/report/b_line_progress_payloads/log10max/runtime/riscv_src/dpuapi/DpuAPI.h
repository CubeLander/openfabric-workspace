#include <stdint.h>
#include "micc_com_def.h"
#include "pe_com_def.h"
#include "inst_def.h"
#include "dma_com_def.h"
#include "mem_com_def.h"

#define CBUF_CONFIG_SIZE 0x14e9000
#define MICC_CONFIG_SIZE 0x820ce0

// dma mode, copy from dma_com_def.h
#define DMA_SIMPLE_MODE 0
#define DMA_SIMD128_MODE 1
#define DMA_SIMD64_MODE 2
#define DMA_SIMD32_MODE 3
#define DMA_SIMD16_MODE 4
#define DMA_INT8_TRS_MODE 5
#define DMA_INT8_TRM_MODE 6
#define DMA_FP16_TRM_MODE 7

#define MX32_FP16 0x10
#define MX64N_FP16 0x20
#define MX32_INT8 0x30
#define MX64_INT8 0x40
#define MX128N_INT8 0x50

#define FMX_FIXED    0x100
#define FMX_MIRROR   0x200
#define FM64N_FIXED  0x300
#define FM64N_MIRROR 0x400
#define FMX_REPEAT   0x500
#define FM64N_REPEAT 0x600

#define FPTRANS_152 0x1000
#define FPTRANS_143 0x3000

#ifndef GET_SIMD_FROM_MODE
#define GET_SIMD_FROM_MODE(mode) (1 << (8 - (mode)))
#endif

typedef struct {
    void* MemAddr_Ch0;
    void* MemAddr_Ch1;
    void* SpmAddr0;
    void* SpmAddr1;
    unsigned x_slice;
    unsigned y_slice;
    unsigned x_full;
    unsigned Trans_Direc;
    unsigned Trans_Mode;
    unsigned Channel_Mask;
    unsigned x_slice1;
    unsigned y_slice1;
    unsigned x_full1;
    unsigned Trans_Direc1;
    unsigned Trans_Mode1;
    unsigned nx0;
    unsigned ny0;
    unsigned mx0;
    unsigned my0;
    unsigned array_num0;
    unsigned nx1;
    unsigned ny1;
    unsigned mx1;
    unsigned my1;
    unsigned array_num1;
    unsigned paddingsize0;
    unsigned paddingdatawidth0;
    unsigned fmx0;
    unsigned fmy0;
    unsigned fmnum0;
    unsigned paddingfixeddata0;
    unsigned paddingsize1;
    unsigned paddingdatawidth1;
    unsigned fmx1;
    unsigned fmy1;
    unsigned fmnum1;
    unsigned paddingfixeddata1;
    unsigned FP8Trans0;
    unsigned FP8Trans1;
} dma_transfer_conf;

int DPU_Transfer(dma_transfer_conf* conf);
int DPU_Transfer_Detailed(dma_transfer_conf* conf);
int DPU_SpmTransfer(void* MemAddr_Ch0, void* MemAddr_Ch1, void* SpmAddr0, void* SpmAddr1,
                    unsigned x_slice, unsigned y_slice, unsigned x_full,
                    unsigned Trans_Direc, unsigned Trans_Mode, unsigned Channel_Mask);
int DPU_SpmTransfer_Single(void* MemAddr_Ch0, void* MemAddr_Ch1, void* SpmAddr0, void* SpmAddr1,
                           unsigned x_slice, unsigned y_slice, unsigned x_full,
                           unsigned Trans_Direc, unsigned Trans_Mode, unsigned Channel_Mask);
int DPU_CbufTransfer(void* MemAddr);
int DPU_MiccTransfer(void* MemAddr);
int DPU_Cbuf_ISTC_Transfer(void* MemAddr);
int DPU_DMATransferFinish(int flag);
int DPU_Kernel_Start(int inst_reload, int task_num, void* instance_base,
                     unsigned instance_base_noneed, int buf_num, int time_type);
int DPU_Kernel_Wait_Finish(int buf_num);
int DPU_App_Finish();
unsigned long MICC_Init_Time();
unsigned long MICC_Exe_Time();
unsigned long DMA_Start_Time();
unsigned long DMA_Finish_Time();
unsigned long DMA_Transfer_Time();
