#define softmax0_input0_SIZE 32768
#define softmax0_output0_SIZE 32768

#define softmax0_input0_SIZE_app 32768
#define softmax0_output0_SIZE_app 32768
#define rope0_output0_SIZE_app 0
#define rmsnorm_output_app 0
static int rmsnorm_output_dim[3] = {0,0,0};

#define MEM_softmax0_input0_ADDR 0
#define MEM_softmax0_output0_ADDR 0

#define SPM_softmax0_input0_ADDR 0
#define SPM_softmax0_output0_ADDR 524288
#define SPM_SUM_ADDR 32768
#define softmax_batch 64

#define LARGE_SCALE 0
#define INPUT_BATCH_SIZE 1
#define APP_NUM 1
#define SUBTASK_NUM 2
#define TASK_NUM 1
#define PE_NUM_BASE 1
static int input_group_base[1] = {256};
static int output_group_base[1] = {256};
static int PE[16] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15};
static int PER_TASK_PE_NUMBER[4] = {16, 16, 16, 16};
static int PER_TASK_INSTANCE_NUMBER[4] = {1, 1, 1, 1};
static int task_order[4] = {0, 1, 2, 3};
static int PER_INSTANCE_STATEMENT_NUMBER[1] = {64};

#ifdef RTL_SIM
static uint64_t softmax0_input0_ddrStartAddr[1] = {
0, };
#else
static unsigned softmax0_input0_ddrStartAddr[1] = {
0, };
#endif
static unsigned softmax0_input0_spmStartAddr[1] = {
0, };
static unsigned softmax0_input0_x_Slice[1] = {
131072, };
static unsigned softmax0_input0_y_Slice[1] = {
1, };
static unsigned softmax0_input0_x_Full[1] = {
131072, };
static unsigned softmax0_input0_regular_mark[1] = {
0, };
static unsigned softmax0_input0_regular_conf[1][4] = {
{0, 0, 0, 0},
};
#ifdef RTL_SIM
static uint64_t softmax0_output0_ddrStartAddr[2] = {
0, 524288, };
#else
static unsigned softmax0_output0_ddrStartAddr[2] = {
0, 524288, };
#endif
static unsigned softmax0_output0_spmStartAddr[2] = {
0, 524288, };
static unsigned softmax0_output0_x_Slice[2] = {
0, 131072, };
static unsigned softmax0_output0_y_Slice[2] = {
0, 1, };
static unsigned softmax0_output0_x_Full[2] = {
0, 131072, };
static unsigned softmax0_output0_regular_mark[2] = {
0, 0, };
static unsigned softmax0_output0_regular_conf[2][4] = {
{0, 0, 0, 0},
{0, 0, 0, 0},
};
