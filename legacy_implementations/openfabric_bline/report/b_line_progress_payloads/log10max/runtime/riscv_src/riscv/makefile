CC ?= riscv64-unknown-elf-gcc
OBJDUMP ?= riscv64-unknown-elf-objdump
COMMON_SRC ?= $(SIMICT_ROOT)/gpdpu/users/risc_nn_riscv/common/src
CFLAGS ?= -mabi=lp64d -march=rv64imafdc -static -std=gnu99 -Wno-error=int-conversion
API_SOURCE := ../dpuapi/DpuAPI.c
all: riscv
riscv: testarm.c $(API_SOURCE)
	$(CC) $(CFLAGS) -o $@ testarm.c $(API_SOURCE) -I../dpuapi -I$(COMMON_SRC)
	$(OBJDUMP) -D $@ > riscv.lst || true
clean:
	rm -f riscv riscv.lst
