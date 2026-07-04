#define GEMM_INPUT1_HEIGHT 512
#define GEMM_INPUT1_WIDTH 256
#define GEMM_INPUT2_HEIGHT 256
#define GEMM_INPUT2_WIDTH 1024
#define GEMM_INPUT3_HEIGHT 512
#define GEMM_INPUT3_WIDTH 1024

#define GEMM_INPUT1_HEIGHT_app 512
#define GEMM_INPUT1_WIDTH_app 256
#define GEMM_INPUT2_HEIGHT_app 256
#define GEMM_INPUT2_WIDTH_app 512
#define GEMM_INPUT3_HEIGHT_app 512
#define GEMM_INPUT3_WIDTH_app 512
#define INPUT_BATCH_SIZE 1

#define PE_ROW 4
#define PE_COL 4
#define PE_NUM	16
#define TASK_NUM 4
#define HASCP2CP 1


#define app_M 1
#define app_K 1
#define app_N 2
#define app_batch 1

#define SPM_GEMM_INPUT1_ADDR 0x00000000
#define SPM_GEMM_INPUT2_ADDR (SPM_GEMM_INPUT1_ADDR + GEMM_INPUT1_HEIGHT_app * GEMM_INPUT1_WIDTH_app * (INPUT_BATCH_SIZE / app_batch) * sizeof(short) / sizeof(float))
#define SPM_GEMM_INPUT3_ADDR (SPM_GEMM_INPUT2_ADDR + GEMM_INPUT2_HEIGHT_app * GEMM_INPUT2_WIDTH_app * (INPUT_BATCH_SIZE / app_batch) * sizeof(short) / sizeof(float))
#define SPM_GEMM_OUTPUT1_ADDR   SPM_GEMM_INPUT3_ADDR

#define taskM_num_per_pe 8
#define taskK_num_per_pe 4
#define taskN_num_per_pe 8

static int micc_unit_idx=0;

#ifdef RTL_SIM
typedef unsigned long long int uint64_t;
static uint64_t GEMM_INPUT1_ddrStartAddr_rtl[2][2] = {
{0, 131072},{0, 131072}};
static uint64_t GEMM_INPUT2_ddrStartAddr_rtl[2][2] = {
{0, 262144},{1024, 263168}};
static uint64_t GEMM_INPUT3_ddrStartAddr_rtl[2][2] = {
{0, 524288},{1024, 525312}};
static uint64_t GEMM_OUTPUT1_ddrStartAddr_rtl[3][2] = {
{0, 0},{0, 524288},{1024, 525312}};
#else
static unsigned int GEMM_INPUT1_ddrStartAddr[2][2] = {
{0, 131072},{0, 131072}};
static unsigned int GEMM_INPUT2_ddrStartAddr[2][2] = {
{0, 262144},{1024, 263168}};
static unsigned int GEMM_INPUT3_ddrStartAddr[2][2] = {
{0, 524288},{1024, 525312}};
static unsigned int GEMM_OUTPUT1_ddrStartAddr[3][2] = {
{0, 0},{0, 524288},{1024, 525312}};
#endif
static unsigned int GEMM_INPUT1_spmStartAddr[2][2] = {
{0, 131072},{4194304, 4325376}};
static unsigned int GEMM_INPUT2_spmStartAddr[2][2] = {
{262144, 393216},{4456448, 4587520}};
static unsigned int GEMM_INPUT3_spmStartAddr[2][2] = {
{524288, 786432},{4718592, 4980736}};
static unsigned int GEMM_OUTPUT1_spmStartAddr[3][2] = {
{0, 0},{524288, 786432},{4718592, 4980736}};
static unsigned int GEMM_INPUT1_x_Slice[2] = {
 131072, 131072};
static unsigned int GEMM_INPUT2_x_Slice[2] = {
 1024, 1024};
static unsigned int GEMM_INPUT3_x_Slice[2] = {
 1024, 1024};
static unsigned int GEMM_OUTPUT1_x_Slice[3] = {
0, 1024, 1024};
static unsigned int GEMM_INPUT1_y_Slice[2] = {
 1, 1};
static unsigned int GEMM_INPUT2_y_Slice[2] = {
 128, 128};
static unsigned int GEMM_INPUT3_y_Slice[2] = {
 256, 256};
static unsigned int GEMM_OUTPUT1_y_Slice[3] = {
0, 256, 256};
static unsigned int GEMM_INPUT1_x_Full[2] = {
 131072, 131072};
static unsigned int GEMM_INPUT2_x_Full[2] = {
 2048, 2048};
static unsigned int GEMM_INPUT3_x_Full[2] = {
 2048, 2048};
static unsigned int GEMM_OUTPUT1_x_Full[3] = {
0, 2048, 2048};
static unsigned int GEMM_INPUT1_regular_conf[2][2][4] = {
 { {0, 0, 0, 0}, {0, 0, 0, 0} },
 { {0, 0, 0, 0}, {0, 0, 0, 0} }
};
static unsigned int GEMM_INPUT2_regular_conf[2][2][4] = {
 { {0, 0, 0, 0}, {0, 0, 0, 0} },
 { {0, 0, 0, 0}, {0, 0, 0, 0} }
};
static unsigned int GEMM_INPUT3_regular_conf[2][2][4] = {
 { {0, 0, 0, 0}, {0, 0, 0, 0} },
 { {0, 0, 0, 0}, {0, 0, 0, 0} }
};
static unsigned int GEMM_OUTPUT1_regular_conf[3][2][4] = {
 { {0, 0, 0, 0}, {0, 0, 0, 0} },
 { {0, 0, 0, 0}, {0, 0, 0, 0} },
 { {0, 0, 0, 0}, {0, 0, 0, 0} }
};
static unsigned int GEMM_INPUT1_regular_mark[2] = {
 0, 0};
static unsigned int GEMM_INPUT2_regular_mark[2] = {
 0, 0};
static unsigned int GEMM_INPUT3_regular_mark[2] = {
 0, 0};
static unsigned int GEMM_OUTPUT1_regular_mark[3] = {
0, 0, 0};


static unsigned int OUTPUT_needown_mark[3] = {
0, 1, 1};

