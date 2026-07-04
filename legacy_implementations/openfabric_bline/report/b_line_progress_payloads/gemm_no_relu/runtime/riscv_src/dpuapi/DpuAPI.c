#include "DpuAPI.h"

int DPU_DMATransferFinish(int flag);
int DPU_SpmTransfer_Single(void* MemAddr_Ch0, void* MemAddr_Ch1, void* SpmAddr0, void* SpmAddr1,
                           unsigned x_slice, unsigned y_slice, unsigned x_full,
                           unsigned Trans_Direc, unsigned Trans_Mode, unsigned Channel_Mask);

/**
 * @brief wrapper of DPU_SpmTransfer_Single
 *
 * @param MemAddr_Ch0 single address if simple mode, array of address if simd mode
 * @param MemAddr_Ch1
 * @param SpmAddr0
 * @param SpmAddr1 not used, usually be 0
 * @param x_slice
 * @param y_slice
 * @param x_full
 * @param Trans_Direc
 * @param Trans_Mode
 * @param Channel_Mask
 * @return int
 *
 * note: It always leave the last DPU_DMATransferFinish test to user to make API consistent.
 */
int DPU_SpmTransfer(void* MemAddr_Ch0, void* MemAddr_Ch1, void* SpmAddr0, void* SpmAddr1,
                    unsigned x_slice, unsigned y_slice, unsigned x_full,
                    unsigned Trans_Direc, unsigned Trans_Mode, unsigned Channel_Mask)
{
    unsigned SIMD_Mode = Trans_Mode & 0xfff;
    if (SIMD_Mode == DMA_SIMPLE_MODE || SIMD_Mode == DMA_INT8_TRM || SIMD_Mode == DMA_FP16_TRM) {
        DPU_SpmTransfer_Single(MemAddr_Ch0, MemAddr_Ch1, SpmAddr0, SpmAddr1,
                               x_slice, y_slice, x_full, Trans_Direc, Trans_Mode, Channel_Mask);
    } else {
        unsigned block_size = x_full * y_slice;
        int i_last_trans = -1;
        int simdNum = GET_SIMD_FROM_MODE(SIMD_Mode);
        unsigned* MemAddr_Ch0_ = (unsigned*)MemAddr_Ch0;
        unsigned* MemAddr_Ch1_ = (unsigned*)MemAddr_Ch1;

        if (Channel_Mask == 0) {
            for (int i = 0; i < simdNum; ++i) {
                if (i < simdNum - 1 && (MemAddr_Ch0_[i + 1] - MemAddr_Ch0_[i]) == block_size) {
                    continue;
                } else {
                    DPU_SpmTransfer_Single((void*)(MemAddr_Ch0_[i_last_trans + 1]), MemAddr_Ch1,
                                           SpmAddr0, SpmAddr1, x_slice,
                                           (unsigned)(y_slice * (i - i_last_trans)), x_full,
                                           Trans_Direc, Trans_Mode, Channel_Mask);
                    if (i < simdNum - 1) {
#if VERBOSE
                        printf("[%s-%d]INFO: waiting for DMA_SPM Trans of simd branch %d ......\n",
                               __func__, __LINE__, i);
#endif
                        while (!DPU_DMATransferFinish(0));
#if VERBOSE
                        printf("[%s-%d]INFO: DMA_SPM Trans of simd branch %d done!\n",
                               __func__, __LINE__, i);
#endif
                    }
                    i_last_trans = i;
                }
            }
        } else if (Channel_Mask == 1) {
            for (int i = 0; i < simdNum; ++i) {
                if (i < simdNum - 1 && (MemAddr_Ch1_[i + 1] - MemAddr_Ch1_[i]) == block_size) {
                    continue;
                } else {
                    DPU_SpmTransfer_Single(MemAddr_Ch0, (void*)(MemAddr_Ch1_[i_last_trans + 1]),
                                           SpmAddr0, SpmAddr1, x_slice,
                                           (unsigned)(y_slice * (i - i_last_trans)), x_full,
                                           Trans_Direc, Trans_Mode, Channel_Mask);
                    if (i < simdNum - 1) {
#if VERBOSE
                        printf("[%s-%d]INFO: waiting for DMA_SPM Trans of simd branch %d ......\n",
                               __func__, __LINE__, i);
#endif
                        while (!DPU_DMATransferFinish(1));
#if VERBOSE
                        printf("[%s-%d]INFO: DMA_SPM Trans of simd branch %d done!\n",
                               __func__, __LINE__, i);
#endif
                    }
                    i_last_trans = i;
                }
            }
        } else if (Channel_Mask == 2) {
            for (int i = 0; i < simdNum / 2; ++i) {
                DPU_SpmTransfer_Single((void*)(MemAddr_Ch0_[i]), (void*)(MemAddr_Ch1_[i]),
                                       SpmAddr0, SpmAddr1, x_slice, y_slice, x_full,
                                       Trans_Direc, Trans_Mode, Channel_Mask);
                if (i < simdNum / 2 - 1) {
#if VERBOSE
                    printf("[%s-%d]INFO: waiting for DMA_SPM Trans of simd branch %d ......\n",
                           __func__, __LINE__, i);
#endif
                    while (!DPU_DMATransferFinish(2));
#if VERBOSE
                    printf("[%s-%d]INFO: DMA_SPM Trans of simd branch %d done!\n",
                           __func__, __LINE__, i);
#endif
                }
            }
        }
    }
}

/**
 * @brief previous DPU_SpmTransfer, now only support simple trans mode in DFGPU-E
 *
 * @param MemAddr_Ch0 MemAddr now should be single address(shouldn't be array of address any more for it was for SIMD trans mode)
 * @param MemAddr_Ch1
 * @param SpmAddr0
 * @param SpmAddr1
 * @param x_slice Byte as unit
 * @param y_slice
 * @param x_full
 * @param Trans_Direc
 * @param Trans_Mode
 * @param Channel_Mask
 * @return int
 */
int DPU_SpmTransfer_Single(void* MemAddr_Ch0, void* MemAddr_Ch1, void* SpmAddr0, void* SpmAddr1,
                           unsigned x_slice, unsigned y_slice, unsigned x_full,
                           unsigned Trans_Direc, unsigned Trans_Mode, unsigned Channel_Mask)
{
    unsigned Trans_Mode_dma = 0; ///< SIMD trans mode are now deprecated, DMA now only has simple mode
    unsigned SIMD_Mode = Trans_Mode & 0xfff;
    unsigned FP8Trans_Mode = Trans_Mode & 0xf000;
    *(unsigned*)SPM_SIMD_MODE = SIMD_Mode;

    if (Channel_Mask == 0) {
        if (Trans_Mode_dma == 0) {
            *(unsigned*)DMA_CHANNEL_MASK = 0; // channel 0
            *(unsigned*)DMA_TRANS_MODE0 = FP8Trans_Mode; // simple mode
            *(unsigned*)DMA_TRANS_DIREC0 = (unsigned)Trans_Direc; // ddr to cbuf
            *(unsigned*)DMA_DDR_ADDR0 = (unsigned)MemAddr_Ch0;
            *(unsigned*)DMA_INACC_ADDR0 = (unsigned)SpmAddr0;
            *(unsigned*)DMA_X_SLICE0 = (unsigned)x_slice;
            *(unsigned*)DMA_Y_SLICE0 = (unsigned)y_slice;
            *(unsigned*)DMA_X_FULL0 = (unsigned)x_full;
            *(unsigned*)DMA_START0 = 2;
            *(unsigned*)DMA_START1 = 0; // not use channel1
        } else {
            printf("only use channel %d,only support simple mode\n", Channel_Mask);
        }
    }

    if (Channel_Mask == 1) {
        if (Trans_Mode_dma == 0) {
            *(unsigned*)DMA_CHANNEL_MASK = 1; // channel 1
            *(unsigned*)DMA_TRANS_MODE1 = FP8Trans_Mode; // simple mode
            *(unsigned*)DMA_TRANS_DIREC1 = (unsigned)Trans_Direc; // ddr to cbuf
            // *(unsigned*)DMA_DDR_ADDR16 = (unsigned)MemAddr_Ch1;
            *(unsigned*)DMA_DDR_ADDR1 = (unsigned)MemAddr_Ch1;
            *(unsigned*)DMA_INACC_ADDR1 = (unsigned)SpmAddr1;
            *(unsigned*)DMA_X_SLICE1 = (unsigned)x_slice;
            *(unsigned*)DMA_Y_SLICE1 = (unsigned)y_slice;
            *(unsigned*)DMA_X_FULL1 = (unsigned)x_full;
            *(unsigned*)DMA_START0 = 0;
            *(unsigned*)DMA_START1 = 2; // use channel1
        } else {
            printf("only use channel %d,only support simple mode\n", Channel_Mask);
        }
    }

    if (Channel_Mask == 2) {
        *(unsigned*)DMA_CHANNEL_MASK = Channel_Mask; // two channel
        *(unsigned*)DMA_INACC_ADDR0 = (unsigned)SpmAddr0;
        *(unsigned*)DMA_X_SLICE0 = (unsigned)x_slice;
        *(unsigned*)DMA_Y_SLICE0 = (unsigned)y_slice;
        *(unsigned*)DMA_X_FULL0 = (unsigned)x_full;
        *(unsigned*)DMA_TRANS_DIREC0 = (unsigned)Trans_Direc;
        *(unsigned*)DMA_TRANS_MODE0 = (unsigned)FP8Trans_Mode;
        *(unsigned*)DMA_INACC_ADDR1 = (unsigned)SpmAddr1;
        *(unsigned*)DMA_X_SLICE1 = (unsigned)x_slice;
        *(unsigned*)DMA_Y_SLICE1 = (unsigned)y_slice;
        *(unsigned*)DMA_X_FULL1 = (unsigned)x_full;
        *(unsigned*)DMA_TRANS_DIREC1 = (unsigned)Trans_Direc;
        *(unsigned*)DMA_TRANS_MODE1 = (unsigned)FP8Trans_Mode;

        if (Trans_Mode_dma == 0) {
            long Data_Size = x_slice * y_slice;
            (void)Data_Size;
            *(unsigned*)DMA_DDR_ADDR0 = (unsigned)MemAddr_Ch0;
            *(unsigned*)DMA_DDR_ADDR1 = (unsigned)MemAddr_Ch1;
        } else {
            printf("[%s-%d]ERROR: DMA SIMD32 Trans mode is now deprecated in DFGPU-E!\n",
                   __func__, __LINE__);
            exit(-1);
            long Data_Size = 32 * x_slice * y_slice;
            *(unsigned*)DMA_DDR_ADDR0 = *(unsigned*)MemAddr_Ch0;
            *(unsigned*)DMA_DDR_ADDR1 = *(((unsigned*)(MemAddr_Ch0)) + 1);
            *(unsigned*)DMA_DDR_ADDR2 = *(((unsigned*)(MemAddr_Ch0)) + 2);
            *(unsigned*)DMA_DDR_ADDR3 = *(((unsigned*)(MemAddr_Ch0)) + 3);
            *(unsigned*)DMA_DDR_ADDR4 = *(((unsigned*)(MemAddr_Ch0)) + 4);
            *(unsigned*)DMA_DDR_ADDR5 = *(((unsigned*)(MemAddr_Ch0)) + 5);
            *(unsigned*)DMA_DDR_ADDR6 = *(((unsigned*)(MemAddr_Ch0)) + 6);
            *(unsigned*)DMA_DDR_ADDR7 = *(((unsigned*)(MemAddr_Ch0)) + 7);
            *(unsigned*)DMA_DDR_ADDR8 = *(((unsigned*)(MemAddr_Ch0)) + 8);
            *(unsigned*)DMA_DDR_ADDR9 = *(((unsigned*)(MemAddr_Ch0)) + 9);
            *(unsigned*)DMA_DDR_ADDR10 = *(((unsigned*)(MemAddr_Ch0)) + 10);
            *(unsigned*)DMA_DDR_ADDR11 = *(((unsigned*)(MemAddr_Ch0)) + 11);
            *(unsigned*)DMA_DDR_ADDR12 = *(((unsigned*)(MemAddr_Ch0)) + 12);
            *(unsigned*)DMA_DDR_ADDR13 = *(((unsigned*)(MemAddr_Ch0)) + 13);
            *(unsigned*)DMA_DDR_ADDR14 = *(((unsigned*)(MemAddr_Ch0)) + 14);
            *(unsigned*)DMA_DDR_ADDR15 = *(((unsigned*)(MemAddr_Ch0)) + 15);
#if 0
            if (Trans_Direc == 1)
                *(unsigned*)DMA_INACC_ADDR1 = (unsigned)SpmAddr + Data_Size / 2;
            else
                *(unsigned*)DMA_INACC_ADDR1 = (unsigned)SpmAddr;
#endif
            *(unsigned*)DMA_DDR_ADDR16 = *(unsigned*)MemAddr_Ch1;
            *(unsigned*)DMA_DDR_ADDR17 = *(((unsigned*)(MemAddr_Ch1)) + 1);
            *(unsigned*)DMA_DDR_ADDR18 = *(((unsigned*)(MemAddr_Ch1)) + 2);
            *(unsigned*)DMA_DDR_ADDR19 = *(((unsigned*)(MemAddr_Ch1)) + 3);
            *(unsigned*)DMA_DDR_ADDR20 = *(((unsigned*)(MemAddr_Ch1)) + 4);
            *(unsigned*)DMA_DDR_ADDR21 = *(((unsigned*)(MemAddr_Ch1)) + 5);
            *(unsigned*)DMA_DDR_ADDR22 = *(((unsigned*)(MemAddr_Ch1)) + 6);
            *(unsigned*)DMA_DDR_ADDR23 = *(((unsigned*)(MemAddr_Ch1)) + 7);
            *(unsigned*)DMA_DDR_ADDR24 = *(((unsigned*)(MemAddr_Ch1)) + 8);
            *(unsigned*)DMA_DDR_ADDR25 = *(((unsigned*)(MemAddr_Ch1)) + 9);
            *(unsigned*)DMA_DDR_ADDR26 = *(((unsigned*)(MemAddr_Ch1)) + 10);
            *(unsigned*)DMA_DDR_ADDR27 = *(((unsigned*)(MemAddr_Ch1)) + 11);
            *(unsigned*)DMA_DDR_ADDR28 = *(((unsigned*)(MemAddr_Ch1)) + 12);
            *(unsigned*)DMA_DDR_ADDR29 = *(((unsigned*)(MemAddr_Ch1)) + 13);
            *(unsigned*)DMA_DDR_ADDR30 = *(((unsigned*)(MemAddr_Ch1)) + 14);
            *(unsigned*)DMA_DDR_ADDR31 = *(((unsigned*)(MemAddr_Ch1)) + 15);
        }

        *(unsigned*)DMA_START0 = 2;
        *(unsigned*)DMA_START1 = 2;
    }
}

int DPU_CbufTransfer(void* MemAddr)
{
    // simple mode trans
    *(unsigned*)DMA_CHANNEL_MASK = 2; // two channel
    *(unsigned*)DMA_TRANS_MODE0 = 0; // simple mode
    *(unsigned*)DMA_TRANS_DIREC0 = 2; // ddr to cbuf
    *(unsigned*)DMA_DDR_ADDR0 = (unsigned)MemAddr;
    // *(unsigned*)DMA_INACC_ADDR0 = 0x00600000;
    *(unsigned*)DMA_INACC_ADDR0 = (unsigned)CBUF_INST_BASE;
    // *(unsigned*)DMA_Y_SLICE0 = 0x88000;
    *(unsigned*)DMA_X_SLICE0 = 0x1298500;
    // *(unsigned*)DMA_X_SLICE0 = 0x1188000;
    *(unsigned*)DMA_Y_SLICE0 = 1;
    *(unsigned*)DMA_X_FULL0 = 0x1298500;
    // *(unsigned*)DMA_X_FULL0 = 0x1188000;
    *(unsigned*)DMA_TRANS_MODE1 = 0; // simple mode
    *(unsigned*)DMA_TRANS_DIREC1 = 2; // ddr to cbuf
    // *(unsigned*)DMA_INACC_ADDR1 = 0x00688000;
    *(unsigned*)DMA_DDR_ADDR16 = (unsigned)MemAddr;
    *(unsigned*)DMA_INACC_ADDR1 = (unsigned)CBUF_BLCK_BASE;
    *(unsigned*)DMA_X_SLICE1 = 0x141500;
    *(unsigned*)DMA_Y_SLICE1 = 1;
    *(unsigned*)DMA_X_FULL1 = 0x141500;
    *(unsigned*)DMA_START0 = 2;
    *(unsigned*)DMA_START1 = 2;
}

int DPU_Cbuf_ISTC_Transfer(void* MemAddr)
{
    // simple mode trans
    *(unsigned*)DMA_CHANNEL_MASK = 0; // channel 0
    *(unsigned*)DMA_TRANS_MODE0 = 0; // simple mode
    *(unsigned*)DMA_TRANS_DIREC0 = 2; // ddr to cbuf
    *(unsigned*)DMA_DDR_ADDR0 = (unsigned)MemAddr;
    *(unsigned*)DMA_INACC_ADDR0 = (unsigned)CBUF_ISTC_BASE;
    *(unsigned*)DMA_X_SLICE0 = 0x100500;
    *(unsigned*)DMA_Y_SLICE0 = 1;
    *(unsigned*)DMA_X_FULL0 = 0x100500;
    *(unsigned*)DMA_START0 = 2;
    *(unsigned*)DMA_START1 = 0; // not use channel1
}

int DPU_MiccTransfer(void* MemAddr)
{
    // simple mode trans use channel 0
    *(unsigned*)DMA_TRANS_MODE0 = 0; // simple mode
    *(unsigned*)DMA_TRANS_DIREC0 = 2; // ddr to cbuf
    *(unsigned*)DMA_CHANNEL_MASK = 0; // channel 0
    *(unsigned*)DMA_DDR_ADDR0 = (unsigned)MemAddr;
    *(unsigned*)DMA_INACC_ADDR0 = (unsigned)MICC_BASE_ADDR;
    *(unsigned*)DMA_X_SLICE0 = 0x480;
    *(unsigned*)DMA_Y_SLICE0 = 1;
    *(unsigned*)DMA_X_FULL0 = 0x480;
    *(unsigned*)DMA_START0 = 2;
    *(unsigned*)DMA_START1 = 0; // not use channel1
}

int DPU_DMATransferFinish(int flag)
{
    // 0 only use channel 0, 1 only use channel 1, 2 use dual channel
    if (flag == 0) {
        if (*(unsigned*)DMA_TRANS_DONE0 == 1) {
            *(unsigned*)DMA_TRANS_DONE0 = 2;
            return 1; // trans done
        } else {
            return 0;
        }
    } else if (flag == 1) {
        if (*(unsigned*)DMA_TRANS_DONE1 == 1) {
            *(unsigned*)DMA_TRANS_DONE1 = 2;
            return 1; // trans done
        } else {
            return 0;
        }
    } else {
        if ((*(unsigned*)DMA_TRANS_DONE0 == 1) && (*(unsigned*)DMA_TRANS_DONE1 == 1)) {
            *(unsigned*)DMA_TRANS_DONE0 = 2;
            *(unsigned*)DMA_TRANS_DONE1 = 2;
            return 1; // trans done
        } else {
            return 0;
        }
    }
}

unsigned long DMA_Start_Time()
{
    unsigned long dma_start_time = *(unsigned*)DMA_START_TIME;
    return dma_start_time;
}

unsigned long DMA_Finish_Time()
{
    unsigned long dma_finish_time = *(unsigned*)DMA_FINISH_TIME;
    return dma_finish_time;
}

unsigned long DMA_Transfer_Time()
{
    unsigned long dma_transfer_time = *(unsigned*)DMA_TRANSFER_TIME;
    return dma_transfer_time;
}

unsigned long MICC_Init_Time()
{
    unsigned long init_time = *(unsigned*)MICC_INIT_TIME;
    return init_time;
}

unsigned long MICC_Exe_Time()
{
    unsigned long exe_time = *(unsigned*)MICC_EXE_TIME;
    return exe_time;
}

int DPU_Kernel_Start(int inst_reload, int task_num, void* instance_base,
                     unsigned instance_base_noneed, int buf_num, int time_type)
{
    int task_enable;
    switch (task_num) {
    case 1:
        task_enable = 1;
        break;
    case 2:
        task_enable = 3;
        break;
    case 3:
        task_enable = 7;
        break;
    case 4:
        task_enable = 15;
        break;
    default:
        task_enable = 0;
    }

    *(unsigned*)MICC_INSTANCE_BASE = (unsigned)instance_base;
    *(unsigned*)MICC_INSTANCE_BASE_NONEED = (unsigned)instance_base_noneed;
    if (buf_num) {
        *(unsigned*)MICC_BUF1_INST = (unsigned)inst_reload;
        *(unsigned*)MICC_BUF1_TASK = (unsigned)task_enable;
        // *(unsigned*)MICC_TIME_TYPE = (unsigned)time_type;
        *(unsigned*)MICC_BUF1_START = 1;
    } else {
        *(unsigned*)MICC_BUF0_INST = (unsigned)inst_reload;
        *(unsigned*)MICC_BUF0_TASK = (unsigned)task_enable;
        // *(unsigned*)MICC_TIME_TYPE = (unsigned)time_type;
        *(unsigned*)MICC_BUF0_START = 1;
    }
    return 1;
}

int DPU_Kernel_Wait_Finish(int buf_num)
{
    if (buf_num) {
        if (*(unsigned*)MICC_BUF1_FINISH == 1)
            return 1; // trans done
        else
            return 0;
    } else {
        if (*(unsigned*)MICC_BUF0_FINISH == 1)
            return 1; // trans done
        else
            return 0;
    }
}

int DPU_App_Finish()
{
    *(unsigned*)MICC_APP_FINISH = 1;
    return 1;
}

int DPU_Transfer(dma_transfer_conf* conf)
{
    unsigned SIMD = conf->Trans_Mode & 0xf;
    unsigned REGULAR = conf->Trans_Mode & 0xff0;
    printf("%s:%s:%d, Trans Mode:%d, REGULAR:%d, MemAddr_Ch0:%x, SpmAddr0:%x\n",
           __FILE__, __func__, __LINE__, conf->Trans_Mode, REGULAR,
           conf->MemAddr_Ch0, conf->SpmAddr0);
    *(unsigned*)SPM_SIMD_MODE = SIMD;
    if (REGULAR == 0) {
        DPU_SpmTransfer((void*)conf->MemAddr_Ch0, (void*)conf->MemAddr_Ch1,
                        (void*)conf->SpmAddr0, (void*)conf->SpmAddr1,
                        conf->x_slice, conf->y_slice, conf->x_full,
                        conf->Trans_Direc, conf->Trans_Mode, conf->Channel_Mask);
    } else {
        if (conf->Channel_Mask == 0) {
            // if (REGULAR != 0) // regular mode
            // {
            *(unsigned*)DMA_CHANNEL_MASK = 0; // channel 0
            *(unsigned*)DMA_TRANS_MODE0 = (unsigned)(conf->Trans_Mode & 0xfff0);
            *(unsigned*)DMA_TRANS_DIREC0 = (unsigned)conf->Trans_Direc;
            *(unsigned*)DMA_DDR_ADDR0 = (unsigned)conf->MemAddr_Ch0;
            *(unsigned*)DMA_INACC_ADDR0 = (unsigned)conf->SpmAddr0;
            *(unsigned*)DMA_X_SLICE0 = (unsigned)conf->x_slice;
            *(unsigned*)DMA_Y_SLICE0 = (unsigned)conf->y_slice;
            *(unsigned*)DMA_X_FULL0 = (unsigned)conf->x_full;
            *(unsigned*)DMA_NX0 = (unsigned)conf->nx0;
            *(unsigned*)DMA_NY0 = (unsigned)conf->ny0;
            *(unsigned*)DMA_MX0 = (unsigned)conf->mx0;
            *(unsigned*)DMA_MY0 = (unsigned)conf->my0;
            *(unsigned*)DMA_ARRAY_NUM0 = (unsigned)conf->array_num0;
            *(unsigned*)DMA_PADDINGSIZE0 = (unsigned)conf->paddingsize0;
            *(unsigned*)DMA_PADDINGDATAWIDTH0 = (unsigned)conf->paddingdatawidth0;
            *(unsigned*)DMA_FMX0 = (unsigned)conf->fmx0;
            *(unsigned*)DMA_FMY0 = (unsigned)conf->fmy0;
            *(unsigned*)DMA_FMNUM0 = (unsigned)conf->fmnum0;
            *(unsigned*)DMA_PADDINGFIXEDDATA0 = (unsigned)conf->paddingfixeddata0;
            *(unsigned*)DMA_START0 = 2;
            *(unsigned*)DMA_START1 = 0; // not use channel1
            // } else
            //     printf("only use channel %d,only support regular mode\n", conf->Channel_Mask);
        }

        if (conf->Channel_Mask == 1) {
            // if (REGULAR != 0) // regular mode
            // {
            *(unsigned*)DMA_CHANNEL_MASK = 1; // channel 1
            *(unsigned*)DMA_TRANS_MODE1 = (unsigned)(conf->Trans_Mode & 0xfff0);
            *(unsigned*)DMA_TRANS_DIREC1 = (unsigned)conf->Trans_Direc;
            *(unsigned*)DMA_DDR_ADDR1 = (unsigned)conf->MemAddr_Ch1;
            *(unsigned*)DMA_INACC_ADDR1 = (unsigned)conf->SpmAddr1;
            *(unsigned*)DMA_X_SLICE1 = (unsigned)conf->x_slice;
            *(unsigned*)DMA_Y_SLICE1 = (unsigned)conf->y_slice;
            *(unsigned*)DMA_X_FULL1 = (unsigned)conf->x_full;
            *(unsigned*)DMA_NX1 = (unsigned)conf->nx1;
            *(unsigned*)DMA_NY1 = (unsigned)conf->ny1;
            *(unsigned*)DMA_MX1 = (unsigned)conf->mx1;
            *(unsigned*)DMA_MY1 = (unsigned)conf->my1;
            *(unsigned*)DMA_ARRAY_NUM1 = (unsigned)conf->array_num1;
            *(unsigned*)DMA_PADDINGSIZE1 = (unsigned)conf->paddingsize1;
            *(unsigned*)DMA_PADDINGDATAWIDTH1 = (unsigned)conf->paddingdatawidth1;
            *(unsigned*)DMA_FMX1 = (unsigned)conf->fmx1;
            *(unsigned*)DMA_FMY1 = (unsigned)conf->fmy1;
            *(unsigned*)DMA_FMNUM1 = (unsigned)conf->fmnum1;
            *(unsigned*)DMA_PADDINGFIXEDDATA1 = (unsigned)conf->paddingfixeddata1;
            *(unsigned*)DMA_START0 = 0;
            *(unsigned*)DMA_START1 = 2; // use channel1
            // } else
            //     printf("only use channel %d,only support regular mode\n", conf->Channel_Mask);
        }

        if (conf->Channel_Mask == 2) {
            // if (REGULAR != 0) // regular mode
            // {
            *(unsigned*)DMA_CHANNEL_MASK = 2; // two channel
            *(unsigned*)DMA_TRANS_MODE0 = (unsigned)(conf->Trans_Mode & 0xfff0);
            *(unsigned*)DMA_TRANS_DIREC0 = (unsigned)conf->Trans_Direc;
            *(unsigned*)DMA_DDR_ADDR0 = (unsigned)conf->MemAddr_Ch0;
            *(unsigned*)DMA_INACC_ADDR0 = (unsigned)conf->SpmAddr0;
            *(unsigned*)DMA_X_SLICE0 = (unsigned)conf->x_slice;
            *(unsigned*)DMA_Y_SLICE0 = (unsigned)conf->y_slice;
            *(unsigned*)DMA_X_FULL0 = (unsigned)conf->x_full;
            *(unsigned*)DMA_NX0 = (unsigned)conf->nx0;
            *(unsigned*)DMA_NY0 = (unsigned)conf->ny0;
            *(unsigned*)DMA_MX0 = (unsigned)conf->mx0;
            *(unsigned*)DMA_MY0 = (unsigned)conf->my0;
            *(unsigned*)DMA_ARRAY_NUM0 = (unsigned)conf->array_num0;
            *(unsigned*)DMA_PADDINGSIZE0 = (unsigned)conf->paddingsize0;
            *(unsigned*)DMA_PADDINGDATAWIDTH0 = (unsigned)conf->paddingdatawidth0;
            *(unsigned*)DMA_FMX0 = (unsigned)conf->fmx0;
            *(unsigned*)DMA_FMY0 = (unsigned)conf->fmy0;
            *(unsigned*)DMA_FMNUM0 = (unsigned)conf->fmnum0;
            *(unsigned*)DMA_PADDINGFIXEDDATA0 = (unsigned)conf->paddingfixeddata0;
            *(unsigned*)DMA_TRANS_MODE1 = (unsigned)(conf->Trans_Mode & 0xfff0);
            *(unsigned*)DMA_TRANS_DIREC1 = (unsigned)conf->Trans_Direc;
            *(unsigned*)DMA_DDR_ADDR1 = (unsigned)conf->MemAddr_Ch1;
            *(unsigned*)DMA_INACC_ADDR1 = (unsigned)conf->SpmAddr1;
            *(unsigned*)DMA_X_SLICE1 = (unsigned)conf->x_slice;
            *(unsigned*)DMA_Y_SLICE1 = (unsigned)conf->y_slice;
            *(unsigned*)DMA_X_FULL1 = (unsigned)conf->x_full;
            *(unsigned*)DMA_NX1 = (unsigned)conf->nx1;
            *(unsigned*)DMA_NY1 = (unsigned)conf->ny1;
            *(unsigned*)DMA_MX1 = (unsigned)conf->mx1;
            *(unsigned*)DMA_MY1 = (unsigned)conf->my1;
            *(unsigned*)DMA_ARRAY_NUM1 = (unsigned)conf->array_num1;
            *(unsigned*)DMA_PADDINGSIZE1 = (unsigned)conf->paddingsize1;
            *(unsigned*)DMA_PADDINGDATAWIDTH1 = (unsigned)conf->paddingdatawidth1;
            *(unsigned*)DMA_FMX1 = (unsigned)conf->fmx1;
            *(unsigned*)DMA_FMY1 = (unsigned)conf->fmy1;
            *(unsigned*)DMA_FMNUM1 = (unsigned)conf->fmnum1;
            *(unsigned*)DMA_PADDINGFIXEDDATA1 = (unsigned)conf->paddingfixeddata1;
            *(unsigned*)DMA_START0 = 2;
            *(unsigned*)DMA_START1 = 2;
            // } else
            // {
            //     printf("use 2 channel,only support regular mode\n");
            // }
        }
    }
    return 1;
}

int DPU_Transfer_Detailed(dma_transfer_conf* conf)
{
    *(unsigned*)SPM_SIMD_MODE = 0;

    if (conf->Channel_Mask == 0) {
        *(unsigned*)DMA_CHANNEL_MASK = 0; // channel 0
        *(unsigned*)DMA_TRANS_MODE0 = (unsigned)(conf->Trans_Mode & 0xfff0);
        *(unsigned*)DMA_TRANS_DIREC0 = (unsigned)conf->Trans_Direc;
        *(unsigned*)DMA_DDR_ADDR0 = (unsigned)conf->MemAddr_Ch0;
        *(unsigned*)DMA_INACC_ADDR0 = (unsigned)conf->SpmAddr0;
        *(unsigned*)DMA_X_SLICE0 = (unsigned)conf->x_slice;
        *(unsigned*)DMA_Y_SLICE0 = (unsigned)conf->y_slice;
        *(unsigned*)DMA_X_FULL0 = (unsigned)conf->x_full;
        *(unsigned*)DMA_NX0 = (unsigned)conf->nx0;
        *(unsigned*)DMA_NY0 = (unsigned)conf->ny0;
        *(unsigned*)DMA_MX0 = (unsigned)conf->mx0;
        *(unsigned*)DMA_MY0 = (unsigned)conf->my0;
        *(unsigned*)DMA_ARRAY_NUM0 = (unsigned)conf->array_num0;
        *(unsigned*)DMA_PADDINGSIZE0 = (unsigned)conf->paddingsize0;
        *(unsigned*)DMA_PADDINGDATAWIDTH0 = (unsigned)conf->paddingdatawidth0;
        *(unsigned*)DMA_FMX0 = (unsigned)conf->fmx0;
        *(unsigned*)DMA_FMY0 = (unsigned)conf->fmy0;
        *(unsigned*)DMA_FMNUM0 = (unsigned)conf->fmnum0;
        *(unsigned*)DMA_PADDINGFIXEDDATA0 = (unsigned)conf->paddingfixeddata0;
        *(unsigned*)DMA_START0 = 2;
        *(unsigned*)DMA_START1 = 0; // not use channel1
    }

    if (conf->Channel_Mask == 1) {
        *(unsigned*)DMA_CHANNEL_MASK = 1; // channel 1
        *(unsigned*)DMA_TRANS_MODE1 = (unsigned)(conf->Trans_Mode1 & 0xfff0);
        *(unsigned*)DMA_TRANS_DIREC1 = (unsigned)conf->Trans_Direc1;
        *(unsigned*)DMA_DDR_ADDR1 = (unsigned)conf->MemAddr_Ch1;
        *(unsigned*)DMA_INACC_ADDR1 = (unsigned)conf->SpmAddr1;
        *(unsigned*)DMA_X_SLICE1 = (unsigned)conf->x_slice1;
        *(unsigned*)DMA_Y_SLICE1 = (unsigned)conf->y_slice1;
        *(unsigned*)DMA_X_FULL1 = (unsigned)conf->x_full1;
        *(unsigned*)DMA_NX1 = (unsigned)conf->nx1;
        *(unsigned*)DMA_NY1 = (unsigned)conf->ny1;
        *(unsigned*)DMA_MX1 = (unsigned)conf->mx1;
        *(unsigned*)DMA_MY1 = (unsigned)conf->my1;
        *(unsigned*)DMA_ARRAY_NUM1 = (unsigned)conf->array_num1;
        *(unsigned*)DMA_PADDINGSIZE1 = (unsigned)conf->paddingsize1;
        *(unsigned*)DMA_PADDINGDATAWIDTH1 = (unsigned)conf->paddingdatawidth1;
        *(unsigned*)DMA_FMX1 = (unsigned)conf->fmx1;
        *(unsigned*)DMA_FMY1 = (unsigned)conf->fmy1;
        *(unsigned*)DMA_FMNUM1 = (unsigned)conf->fmnum1;
        *(unsigned*)DMA_PADDINGFIXEDDATA1 = (unsigned)conf->paddingfixeddata1;
        *(unsigned*)DMA_START0 = 0;
        *(unsigned*)DMA_START1 = 2; // use channel1
    }

    if (conf->Channel_Mask == 2) {
        *(unsigned*)DMA_CHANNEL_MASK = 2; // two channel
        *(unsigned*)DMA_TRANS_MODE0 = (unsigned)(conf->Trans_Mode & 0xfff0);
        *(unsigned*)DMA_TRANS_DIREC0 = (unsigned)conf->Trans_Direc;
        *(unsigned*)DMA_DDR_ADDR0 = (unsigned)conf->MemAddr_Ch0;
        *(unsigned*)DMA_INACC_ADDR0 = (unsigned)conf->SpmAddr0;
        *(unsigned*)DMA_X_SLICE0 = (unsigned)conf->x_slice;
        *(unsigned*)DMA_Y_SLICE0 = (unsigned)conf->y_slice;
        *(unsigned*)DMA_X_FULL0 = (unsigned)conf->x_full;
        *(unsigned*)DMA_NX0 = (unsigned)conf->nx0;
        *(unsigned*)DMA_NY0 = (unsigned)conf->ny0;
        *(unsigned*)DMA_MX0 = (unsigned)conf->mx0;
        *(unsigned*)DMA_MY0 = (unsigned)conf->my0;
        *(unsigned*)DMA_ARRAY_NUM0 = (unsigned)conf->array_num0;
        *(unsigned*)DMA_PADDINGSIZE0 = (unsigned)conf->paddingsize0;
        *(unsigned*)DMA_PADDINGDATAWIDTH0 = (unsigned)conf->paddingdatawidth0;
        *(unsigned*)DMA_FMX0 = (unsigned)conf->fmx0;
        *(unsigned*)DMA_FMY0 = (unsigned)conf->fmy0;
        *(unsigned*)DMA_FMNUM0 = (unsigned)conf->fmnum0;
        *(unsigned*)DMA_PADDINGFIXEDDATA0 = (unsigned)conf->paddingfixeddata0;
        *(unsigned*)DMA_TRANS_MODE1 = (unsigned)(conf->Trans_Mode1 & 0xfff0);
        *(unsigned*)DMA_TRANS_DIREC1 = (unsigned)conf->Trans_Direc1;
        *(unsigned*)DMA_DDR_ADDR1 = (unsigned)conf->MemAddr_Ch1;
        *(unsigned*)DMA_INACC_ADDR1 = (unsigned)conf->SpmAddr1;
        *(unsigned*)DMA_X_SLICE1 = (unsigned)conf->x_slice1;
        *(unsigned*)DMA_Y_SLICE1 = (unsigned)conf->y_slice1;
        *(unsigned*)DMA_X_FULL1 = (unsigned)conf->x_full1;
        *(unsigned*)DMA_NX1 = (unsigned)conf->nx1;
        *(unsigned*)DMA_NY1 = (unsigned)conf->ny1;
        *(unsigned*)DMA_MX1 = (unsigned)conf->mx1;
        *(unsigned*)DMA_MY1 = (unsigned)conf->my1;
        *(unsigned*)DMA_ARRAY_NUM1 = (unsigned)conf->array_num1;
        *(unsigned*)DMA_PADDINGSIZE1 = (unsigned)conf->paddingsize1;
        *(unsigned*)DMA_PADDINGDATAWIDTH1 = (unsigned)conf->paddingdatawidth1;
        *(unsigned*)DMA_FMX1 = (unsigned)conf->fmx1;
        *(unsigned*)DMA_FMY1 = (unsigned)conf->fmy1;
        *(unsigned*)DMA_FMNUM1 = (unsigned)conf->fmnum1;
        *(unsigned*)DMA_PADDINGFIXEDDATA1 = (unsigned)conf->paddingfixeddata1;
        *(unsigned*)DMA_START0 = 2;
        *(unsigned*)DMA_START1 = 2;
    }
    return 1;
}
