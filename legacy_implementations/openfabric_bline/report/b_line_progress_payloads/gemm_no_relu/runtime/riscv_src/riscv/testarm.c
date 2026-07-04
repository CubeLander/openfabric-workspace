#include "DpuAPI.h"

#ifdef RTL_SIM
// for RTL
#include "conf.h"
#include "data.h"
#include "serial.h"
#else
// for simulator
#include <stdio.h>
#include "../csv_generate/conf.h"
#include "../spm_data/data.h"
#endif

#define DEBUG 0
#define DMA_MATRIX_WIDTH 32

void DMA_Transfer_input(unsigned ddr_start_addr0,
						unsigned ddr_start_addr1,
						unsigned spm_start_addr0,
						unsigned spm_start_addr1,
						unsigned x_slice,
						unsigned y_slice,
						unsigned x_full,
						unsigned trans_mode,
						unsigned trans_direc,
						unsigned channel_mask,
						unsigned regular_mark,
						unsigned (*regular_conf)[4],
						unsigned batch_num) {
	int num0,num1;
	if(batch_num == 1){
		num0 = 1;
		num1 = 1;
	} else if(batch_num % 2 == 0){
		num0 = batch_num / 2;
		num1 = batch_num / 2;
	}else {
		num0 = (batch_num + 1) / 2;
		num1 = (batch_num - 1) / 2;
	}
	if (regular_mark == 1 && regular_conf[1][3] == 0) {
		channel_mask = 0;
		if (app_M != 1) {
			regular_conf[0][1] = 64;
		}
	}
	if (!regular_mark) {
		dma_transfer_conf* conf_mem2spm_a = (dma_transfer_conf*)malloc(sizeof(dma_transfer_conf));
		conf_mem2spm_a->MemAddr_Ch0 = ddr_start_addr0;
		conf_mem2spm_a->SpmAddr0 = spm_start_addr0;
		conf_mem2spm_a->x_slice = x_slice;
		conf_mem2spm_a->y_slice = y_slice * num0;
		conf_mem2spm_a->x_full = x_full;
		conf_mem2spm_a->Trans_Direc = trans_direc;
		conf_mem2spm_a->Trans_Mode = 0;
		conf_mem2spm_a->Channel_Mask = channel_mask;
		conf_mem2spm_a->MemAddr_Ch1 = ddr_start_addr1;
		conf_mem2spm_a->SpmAddr1 = spm_start_addr1;
		conf_mem2spm_a->x_slice1 = x_slice;
		conf_mem2spm_a->y_slice1 = y_slice * num1;
		conf_mem2spm_a->x_full1 = x_full;
		conf_mem2spm_a->Trans_Mode1 = 0;
		DPU_Transfer_Detailed(conf_mem2spm_a);
	} else {
		dma_transfer_conf* conf_mem2spm_a = (dma_transfer_conf*)malloc(sizeof(dma_transfer_conf));
		conf_mem2spm_a->MemAddr_Ch0 = ddr_start_addr0;
		conf_mem2spm_a->SpmAddr0 = spm_start_addr0;
		conf_mem2spm_a->x_slice = x_slice;
		conf_mem2spm_a->y_slice = y_slice * num0;
		conf_mem2spm_a->x_full = x_full;
		conf_mem2spm_a->Trans_Direc = trans_direc;
		conf_mem2spm_a->Trans_Mode = MX64N_FP16;
		conf_mem2spm_a->Channel_Mask = channel_mask;
		conf_mem2spm_a->mx0 = regular_conf[0][0];
		conf_mem2spm_a->my0 = regular_conf[0][1];
		conf_mem2spm_a->nx0 = regular_conf[0][2];
		conf_mem2spm_a->ny0 = regular_conf[0][3];
		conf_mem2spm_a->array_num0 = num0;
		conf_mem2spm_a->MemAddr_Ch1 = ddr_start_addr1;
		conf_mem2spm_a->SpmAddr1 = spm_start_addr1;
		conf_mem2spm_a->x_slice1 = x_slice;
		conf_mem2spm_a->y_slice1 = y_slice * num1;
		conf_mem2spm_a->x_full1 = x_full;
		conf_mem2spm_a->Trans_Mode1 = MX64N_FP16;
		conf_mem2spm_a->mx1 = regular_conf[1][0];
		conf_mem2spm_a->my1 = regular_conf[1][1];
		conf_mem2spm_a->nx1 = regular_conf[1][2];
		conf_mem2spm_a->ny1 = regular_conf[1][3];
		conf_mem2spm_a->array_num1 = num1;
		DPU_Transfer_Detailed(conf_mem2spm_a);
	}
	while (!(DPU_DMATransferFinish(channel_mask)));
}

void DMA_Transfer_output(unsigned ddr_start_addr0,
						unsigned ddr_start_addr1,
						unsigned spm_start_addr0,
						unsigned spm_start_addr1,
						unsigned x_slice,
						unsigned y_slice,
						unsigned x_full,
						unsigned trans_mode,
						unsigned trans_direc,
						unsigned channel_mask,
						unsigned output_regular_mark,
						unsigned (*output_regular_conf)[4],
						unsigned batch_num) {
	int num0,num1;
	if(batch_num == 1){
		num0 = 1;
		num1 = 1;
	} else if(batch_num % 2 == 0){
		num0 = batch_num / 2;
		num1 = batch_num / 2;
	}else {
		num0 = (batch_num + 1) / 2;
		num1 = (batch_num - 1) / 2;
	}
	if (output_regular_mark == 1 && output_regular_conf[1][3] == 0) {
		channel_mask = 0;
		if (app_M != 1) {
			output_regular_conf[0][1] = 64;
		}
	}
	if (!output_regular_mark) {
		dma_transfer_conf* conf_spm2mem_c = (dma_transfer_conf*)malloc(sizeof(dma_transfer_conf));
		conf_spm2mem_c->MemAddr_Ch0 = ddr_start_addr0;
		conf_spm2mem_c->SpmAddr0 = spm_start_addr0;
		conf_spm2mem_c->x_slice = x_slice;
		conf_spm2mem_c->y_slice = y_slice * num0;
		conf_spm2mem_c->x_full = x_full;
		conf_spm2mem_c->Trans_Direc = trans_direc;
		conf_spm2mem_c->Trans_Mode = 0;
		conf_spm2mem_c->Channel_Mask = channel_mask;
		conf_spm2mem_c->MemAddr_Ch1 = ddr_start_addr1;
		conf_spm2mem_c->SpmAddr1 = spm_start_addr1;
		conf_spm2mem_c->x_slice1 = x_slice;
		conf_spm2mem_c->y_slice1 = y_slice * num1;
		conf_spm2mem_c->x_full1 = x_full;
		conf_spm2mem_c->Trans_Mode1 = 0;
		DPU_Transfer_Detailed(conf_spm2mem_c);
	} else {
		dma_transfer_conf* conf_spm2mem_c = (dma_transfer_conf*)malloc(sizeof(dma_transfer_conf));
		conf_spm2mem_c->MemAddr_Ch0 = ddr_start_addr0;
		conf_spm2mem_c->SpmAddr0 = spm_start_addr0;
		conf_spm2mem_c->x_slice = x_slice;
		conf_spm2mem_c->y_slice = y_slice * num0;
		conf_spm2mem_c->x_full = x_full;
		conf_spm2mem_c->Trans_Direc = trans_direc;
		conf_spm2mem_c->Trans_Mode = MX64N_FP16;
		conf_spm2mem_c->Channel_Mask = channel_mask;
		conf_spm2mem_c->mx0 = output_regular_conf[0][0];
		conf_spm2mem_c->my0 = output_regular_conf[0][1];
		conf_spm2mem_c->nx0 = output_regular_conf[0][2];
		conf_spm2mem_c->ny0 = output_regular_conf[0][3];
		conf_spm2mem_c->array_num0 = num0;
		conf_spm2mem_c->MemAddr_Ch1 = ddr_start_addr1;
		conf_spm2mem_c->SpmAddr1 = spm_start_addr1;
		conf_spm2mem_c->x_slice1 = x_slice;
		conf_spm2mem_c->y_slice1 = y_slice * num1;
		conf_spm2mem_c->x_full1 = x_full;
		conf_spm2mem_c->Trans_Mode1 = MX64N_FP16;
		conf_spm2mem_c->mx1 = output_regular_conf[1][0];
		conf_spm2mem_c->my1 = output_regular_conf[1][1];
		conf_spm2mem_c->nx1 = output_regular_conf[1][2];
		conf_spm2mem_c->ny1 = output_regular_conf[1][3];
		conf_spm2mem_c->array_num1 = num1;
		DPU_Transfer_Detailed(conf_spm2mem_c);
	}
	while (!(DPU_DMATransferFinish(channel_mask)));
}

int main() {
	int micc_base_addr_noneed[app_batch * app_M * app_N * app_K];
	if(app_M == 1 && app_N == 1){
		micc_base_addr_noneed[0] = 0;
		micc_base_addr_noneed[app_batch * app_M * app_N * app_K - 1] = 1;
		for(int i = 1; i < app_M * app_N * app_K - 1; i++){
			micc_base_addr_noneed[i] = 257;
		}
	}
	// conf
	unsigned simple_mode_trans = 0;
	unsigned simd32_mode_trans = 2;
	unsigned mem_to_spm = 2;
	unsigned spm_to_mem = 0;
	unsigned MEM_GEMM_INPUT1_ADDR = 0x00000000 - 0x0;
	unsigned MEM_GEMM_INPUT2_ADDR = MEM_GEMM_INPUT1_ADDR + GEMM_INPUT1_HEIGHT * GEMM_INPUT1_WIDTH * INPUT_BATCH_SIZE * sizeof(short) - 0x0;
	unsigned MEM_GEMM_INPUT3_ADDR = MEM_GEMM_INPUT2_ADDR + GEMM_INPUT2_HEIGHT * GEMM_INPUT2_WIDTH * INPUT_BATCH_SIZE * sizeof(short) - 0x0;
	unsigned MEM_GEMM_OUTPUT1_ADDR = 0x00000000 - 0x0;
	// transfer inst
	DPU_CbufTransfer((void*)CBUF_DDR_ADDR);
	while (!(DPU_DMATransferFinish(2)));
	printf("transfer inst end\n");
	// transfer conf
	DPU_MiccTransfer((void*)MICC_DDR_ADDR);
	while (!(DPU_DMATransferFinish(0)));
	printf("transfer conf end\n");
	int app_num = 0;
	int i;

	if (app_M != 1 || app_N != 1) {
		for(int b = 0; b < app_batch; b++){
		for (i = 0; i < app_M * app_N * app_K; i++) {
			// transfer data from memory to spm
			if (app_M != 1 && app_K != 1) {
				for (int batch = 0; batch < INPUT_BATCH_SIZE / app_batch; batch++) {
					unsigned ddr_batch = batch * GEMM_INPUT1_HEIGHT * GEMM_INPUT1_WIDTH * sizeof(short);
					unsigned spm_batch = batch * GEMM_INPUT1_HEIGHT_app * GEMM_INPUT1_WIDTH_app * sizeof(short);
					DMA_Transfer_input(
						MEM_GEMM_INPUT1_ADDR + GEMM_INPUT1_ddrStartAddr[app_num][0] + SPM_DDR_ADDR + ddr_batch,
						MEM_GEMM_INPUT1_ADDR + GEMM_INPUT1_ddrStartAddr[app_num][1] + SPM_DDR_ADDR + ddr_batch,
				GEMM_INPUT1_spmStartAddr[app_num][0] + spm_batch, GEMM_INPUT1_spmStartAddr[app_num][1] + spm_batch,
						GEMM_INPUT1_x_Slice[app_num], GEMM_INPUT1_y_Slice[app_num], GEMM_INPUT1_x_Full[app_num],
						simple_mode_trans, mem_to_spm,2, GEMM_INPUT1_regular_mark[app_num],
						GEMM_INPUT1_regular_conf[app_num], 1);
					printf("transfer GEMM_INPUT1 end: app%d, batch%d.\n", app_num, batch);
				}
			} else {
				DMA_Transfer_input(
					MEM_GEMM_INPUT1_ADDR + GEMM_INPUT1_ddrStartAddr[app_num][0] + SPM_DDR_ADDR,
					MEM_GEMM_INPUT1_ADDR + GEMM_INPUT1_ddrStartAddr[app_num][1] + SPM_DDR_ADDR,
					GEMM_INPUT1_spmStartAddr[app_num][0], GEMM_INPUT1_spmStartAddr[app_num][1],
					GEMM_INPUT1_x_Slice[app_num], GEMM_INPUT1_y_Slice[app_num], GEMM_INPUT1_x_Full[app_num],
					simple_mode_trans, mem_to_spm, 2, GEMM_INPUT1_regular_mark[app_num],
					GEMM_INPUT1_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
				printf("transfer GEMM_INPUT1 end: app%d.\n", app_num);
			}

			if (app_K != 1 && app_N != 1) {
				for (int batch = 0; batch < INPUT_BATCH_SIZE / app_batch; batch++) {
					unsigned ddr_batch = batch * GEMM_INPUT2_HEIGHT * GEMM_INPUT2_WIDTH * sizeof(short);
					unsigned spm_batch = batch * GEMM_INPUT2_HEIGHT_app * GEMM_INPUT2_WIDTH_app * sizeof(short);
					DMA_Transfer_input(
						MEM_GEMM_INPUT2_ADDR + GEMM_INPUT2_ddrStartAddr[app_num][0] + SPM_DDR_ADDR + ddr_batch,
						MEM_GEMM_INPUT2_ADDR + GEMM_INPUT2_ddrStartAddr[app_num][1] + SPM_DDR_ADDR + ddr_batch,
				GEMM_INPUT2_spmStartAddr[app_num][0] + spm_batch, GEMM_INPUT2_spmStartAddr[app_num][1] + spm_batch,
						GEMM_INPUT2_x_Slice[app_num], GEMM_INPUT2_y_Slice[app_num], GEMM_INPUT2_x_Full[app_num],
						simple_mode_trans, mem_to_spm, 2, GEMM_INPUT2_regular_mark[app_num],
						GEMM_INPUT2_regular_conf[app_num], 1);
					printf("transfer GEMM_INPUT2 end: app%d, batch%d.\n", app_num, batch);
				}
			} else {
				DMA_Transfer_input(
					MEM_GEMM_INPUT2_ADDR + GEMM_INPUT2_ddrStartAddr[app_num][0] + SPM_DDR_ADDR,
					MEM_GEMM_INPUT2_ADDR + GEMM_INPUT2_ddrStartAddr[app_num][1] + SPM_DDR_ADDR,
					GEMM_INPUT2_spmStartAddr[app_num][0], GEMM_INPUT2_spmStartAddr[app_num][1],
					GEMM_INPUT2_x_Slice[app_num], GEMM_INPUT2_y_Slice[app_num], GEMM_INPUT2_x_Full[app_num],
					simple_mode_trans, mem_to_spm, 2, GEMM_INPUT2_regular_mark[app_num],
					GEMM_INPUT2_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
				printf("transfer GEMM_INPUT2 end: app%d.\n", app_num);
			}

			if (i == 0 || GEMM_INPUT3_ddrStartAddr[app_num][0] != b * (INPUT_BATCH_SIZE / app_batch) * GEMM_INPUT3_HEIGHT * GEMM_INPUT3_WIDTH * sizeof(short)) {
				if (app_M != 1 && app_N != 1) {
					for (int batch = 0; batch < INPUT_BATCH_SIZE / app_batch; batch++) {
						unsigned ddr_batch = batch * GEMM_INPUT3_HEIGHT * GEMM_INPUT3_WIDTH * sizeof(short);
						unsigned spm_batch = batch * GEMM_INPUT3_HEIGHT_app * GEMM_INPUT3_WIDTH_app * sizeof(short);
						DMA_Transfer_input(
							MEM_GEMM_INPUT3_ADDR + GEMM_INPUT3_ddrStartAddr[app_num][0] + SPM_DDR_ADDR + ddr_batch,
							MEM_GEMM_INPUT3_ADDR + GEMM_INPUT3_ddrStartAddr[app_num][1] + SPM_DDR_ADDR + ddr_batch,
							GEMM_INPUT3_spmStartAddr[app_num][0] + spm_batch, GEMM_INPUT3_spmStartAddr[app_num][1] + spm_batch,
							GEMM_INPUT3_x_Slice[app_num], GEMM_INPUT3_y_Slice[app_num], GEMM_INPUT3_x_Full[app_num],
							simple_mode_trans, mem_to_spm, 2, GEMM_INPUT3_regular_mark[app_num],
							GEMM_INPUT3_regular_conf[app_num], 1);
						printf("transfer GEMM_INPUT3 end: app%d, batch%d.\n", app_num, batch);
					}
				} else {
					DMA_Transfer_input(
						MEM_GEMM_INPUT3_ADDR + GEMM_INPUT3_ddrStartAddr[app_num][0] + SPM_DDR_ADDR,
						MEM_GEMM_INPUT3_ADDR + GEMM_INPUT3_ddrStartAddr[app_num][1] + SPM_DDR_ADDR,
						GEMM_INPUT3_spmStartAddr[app_num][0], GEMM_INPUT3_spmStartAddr[app_num][1],
						GEMM_INPUT3_x_Slice[app_num], GEMM_INPUT3_y_Slice[app_num], GEMM_INPUT3_x_Full[app_num],
						simple_mode_trans, mem_to_spm, 2, GEMM_INPUT3_regular_mark[app_num],
						GEMM_INPUT3_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
					printf("transfer GEMM_INPUT3 end: app%d.\n", app_num);
				}
			}

			// kernel start
			if (app_num > 0) {
				while (!DPU_Kernel_Wait_Finish((app_num - 1) % 2));
			}
			printf("kernel start : app %d\n", app_num);
			int inst_reload = app_num > 0 ? 0 : 1;
			DPU_Kernel_Start(inst_reload, TASK_NUM, (void*)(((app_num % 2) * 0x400000) / 4), 0, (app_num % 2), 0);

			// output trans spm to mem
			if (OUTPUT_needown_mark[app_num] == 1) {
				if (app_M != 1 && app_N != 1) {
					for (int batch = 0; batch < INPUT_BATCH_SIZE / app_batch; batch++) {
						unsigned ddr_batch = batch * GEMM_INPUT3_HEIGHT * GEMM_INPUT3_WIDTH * sizeof(short);
						unsigned spm_batch = batch * GEMM_INPUT3_HEIGHT_app * GEMM_INPUT3_WIDTH_app * sizeof(short);
						DMA_Transfer_output(
							MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][0] + SPM_RST_DDR_ADDR + ddr_batch,
							MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][1] + SPM_RST_DDR_ADDR + ddr_batch,
							GEMM_OUTPUT1_spmStartAddr[app_num][0] + spm_batch, GEMM_OUTPUT1_spmStartAddr[app_num][1] + spm_batch,
							GEMM_OUTPUT1_x_Slice[app_num], GEMM_OUTPUT1_y_Slice[app_num], GEMM_OUTPUT1_x_Full[app_num],
							simple_mode_trans, spm_to_mem, 2, GEMM_OUTPUT1_regular_mark[app_num],
							GEMM_OUTPUT1_regular_conf[app_num], 1);
						printf("transfer GEMM_OUTPUT1 end: app%d, batch%d.\n", app_num, batch);
					}
				} else {
					DMA_Transfer_output(
						MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][0] + SPM_RST_DDR_ADDR,
						MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][1] + SPM_RST_DDR_ADDR,
						GEMM_OUTPUT1_spmStartAddr[app_num][0], GEMM_OUTPUT1_spmStartAddr[app_num][1],
						GEMM_OUTPUT1_x_Slice[app_num], GEMM_OUTPUT1_y_Slice[app_num], GEMM_OUTPUT1_x_Full[app_num],
						simple_mode_trans, spm_to_mem, 2, GEMM_OUTPUT1_regular_mark[app_num],
						GEMM_OUTPUT1_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
					printf("transfer GEMM_OUTPUT1 end: app%d.\n", app_num);
				}
			}
			app_num++;
		}
		while (!DPU_Kernel_Wait_Finish((app_num - 1) % 2));
		if (OUTPUT_needown_mark[app_num] == 1) {
			if (app_M != 1 && app_N != 1) {
				for (int batch = 0; batch < INPUT_BATCH_SIZE / app_batch; batch++) {
					unsigned ddr_batch = batch * GEMM_INPUT3_HEIGHT * GEMM_INPUT3_WIDTH * sizeof(short);
					unsigned spm_batch = batch * GEMM_INPUT3_HEIGHT_app * GEMM_INPUT3_WIDTH_app * sizeof(short);
					DMA_Transfer_output(
						MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][0] + SPM_RST_DDR_ADDR + ddr_batch,
						MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][1] + SPM_RST_DDR_ADDR + ddr_batch,
						GEMM_OUTPUT1_spmStartAddr[app_num][0] + spm_batch, GEMM_OUTPUT1_spmStartAddr[app_num][1] + spm_batch,
						GEMM_OUTPUT1_x_Slice[app_num], GEMM_OUTPUT1_y_Slice[app_num], GEMM_OUTPUT1_x_Full[app_num],
						simple_mode_trans, spm_to_mem, 2, GEMM_OUTPUT1_regular_mark[app_num],
						GEMM_OUTPUT1_regular_conf[app_num], 1);
					printf("transfer GEMM_OUTPUT1 end: app%d, batch%d.\n", app_num, batch);
				}
			} else {
				DMA_Transfer_output(
					MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][0] + SPM_RST_DDR_ADDR,
					MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][1] + SPM_RST_DDR_ADDR,
					GEMM_OUTPUT1_spmStartAddr[app_num][0], GEMM_OUTPUT1_spmStartAddr[app_num][1],
					GEMM_OUTPUT1_x_Slice[app_num], GEMM_OUTPUT1_y_Slice[app_num], GEMM_OUTPUT1_x_Full[app_num],
					simple_mode_trans, spm_to_mem, 2, GEMM_OUTPUT1_regular_mark[app_num],
					GEMM_OUTPUT1_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
				printf("transfer GEMM_OUTPUT1 end: app%d.\n", app_num);
			}
		}
		}
		DPU_App_Finish();
		printf("\n");
	} else {
		for(int b = 0; b < app_batch; b++){
		for (i = 0; i < app_M * app_N * app_K; i++) {
			DMA_Transfer_input(MEM_GEMM_INPUT1_ADDR + GEMM_INPUT1_ddrStartAddr[app_num][0] + SPM_DDR_ADDR,
				MEM_GEMM_INPUT1_ADDR + GEMM_INPUT1_ddrStartAddr[app_num][1] + SPM_DDR_ADDR,
								GEMM_INPUT1_spmStartAddr[app_num][0], GEMM_INPUT1_spmStartAddr[app_num][1],
								GEMM_INPUT1_x_Slice[app_num], GEMM_INPUT1_y_Slice[app_num],
								GEMM_INPUT1_x_Full[app_num], simple_mode_trans, mem_to_spm,
								2, GEMM_INPUT1_regular_mark[app_num],
								GEMM_INPUT1_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
			printf("transfer matrix a end %d\n", app_num);

			DMA_Transfer_input(MEM_GEMM_INPUT2_ADDR + GEMM_INPUT2_ddrStartAddr[app_num][0] + SPM_DDR_ADDR,
				MEM_GEMM_INPUT2_ADDR + GEMM_INPUT2_ddrStartAddr[app_num][1] + SPM_DDR_ADDR,
								GEMM_INPUT2_spmStartAddr[app_num][0], GEMM_INPUT2_spmStartAddr[app_num][1],
								GEMM_INPUT2_x_Slice[app_num], GEMM_INPUT2_y_Slice[app_num],
								GEMM_INPUT2_x_Full[app_num], simple_mode_trans, mem_to_spm,
								2, GEMM_INPUT2_regular_mark[app_num],
								GEMM_INPUT2_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
			printf("transfer matrix b end %d\n", app_num);

			if (app_num > 0) {
				while (!DPU_Kernel_Wait_Finish((app_num - 1) % 2));
			}

			if(app_num == 0){
			DMA_Transfer_input(
				MEM_GEMM_INPUT3_ADDR + GEMM_INPUT3_ddrStartAddr[app_num][0] + SPM_DDR_ADDR, 
				MEM_GEMM_INPUT3_ADDR + GEMM_INPUT3_ddrStartAddr[app_num][1] + SPM_DDR_ADDR,
				GEMM_INPUT3_spmStartAddr[app_num][0], GEMM_INPUT3_spmStartAddr[app_num][1],
				GEMM_INPUT3_x_Slice[app_num], GEMM_INPUT3_y_Slice[app_num], GEMM_INPUT3_x_Full[app_num],
				simple_mode_trans, mem_to_spm, 2, GEMM_INPUT3_regular_mark[app_num],
				GEMM_INPUT3_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
			printf("transfer matrix c end %d\n", app_num);
			}
			if (app_num == app_M * app_N * app_K - 1) {
			}

			printf("kernel start : app %d\n", app_num);
			int inst_reload = app_num > 0 ? 0 : 1;
			DPU_Kernel_Start(inst_reload, TASK_NUM,
							(void*)(((app_num % 2) * 0x400000) / 4), micc_base_addr_noneed[app_num],
							(app_num % 2), 0);

			app_num++;
		}
		while (!DPU_Kernel_Wait_Finish((app_num - 1) % 2));
		DMA_Transfer_output(
			MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][0] + SPM_RST_DDR_ADDR, 
			MEM_GEMM_OUTPUT1_ADDR + GEMM_OUTPUT1_ddrStartAddr[app_num][1] + SPM_RST_DDR_ADDR,
			GEMM_OUTPUT1_spmStartAddr[app_num][0], GEMM_OUTPUT1_spmStartAddr[app_num][1],
			GEMM_OUTPUT1_x_Slice[app_num], GEMM_OUTPUT1_y_Slice[app_num], GEMM_OUTPUT1_x_Full[app_num],
			simple_mode_trans, spm_to_mem, 2, GEMM_OUTPUT1_regular_mark[app_num],
			GEMM_OUTPUT1_regular_conf[app_num], INPUT_BATCH_SIZE / app_batch);
		}
		DPU_App_Finish();
		printf("\n");

	}

	return 1;
}
