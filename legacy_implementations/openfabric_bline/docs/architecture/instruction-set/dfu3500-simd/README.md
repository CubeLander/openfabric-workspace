# DFU3500 SIMD 指令材料抽取结果

本目录由 `tools/extract_instruction_docs.py` 从原始 xlsx/docx 生成。
原始材料不做修改。

## 文件

- `xlsx/Sheet1.csv`: 指令列表、pipeline、拍数、imm 字段等。
- `xlsx/Sheet2.csv`: 指令功能和 operand 输入输出说明。
- `OPERAND_LANE_MODEL.md`: 解释 SIMD128 logical operand 与 1024-bit chunk 如何按指令解释成不同 lane。
- `MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`: 记录 A-line runtime 经验补出来的执行上下文语义，尤其是访存 `iteration/base_addr`、伪指令展开、template evidence 与 byte emission 边界。
- `UNCLEAR_SEMANTICS_BACKLOG.md`: 记录暂时不阻塞、等实际遇到再继续研究的指令语义疑点。
- `instruction_cards.jsonl`: 每行一个指令卡片，适合 agent 按 mnemonic 检索。
- `instruction_cards.md`: 人类可读的指令卡片。
- `docx/dfu3500-simd-instruction-doc.md`: docx 正文和表格的 Markdown 抽取。
- `docx/instruction_sections/`: 从 docx 按 mnemonic 切出的原文段落，适合追溯 typed view。
- `docx/media/`: docx 中的图片原样抽取。
- `docx/media_ocr/media_ocr.md`: docx 图片的 OCR 原文，按图片编号排列。
- `docx/media_ocr/media_ocr_index.jsonl`: 每张图片的尺寸、OCR 分数、标签和文本。
- `OCR_DERIVED_NOTES.md`: 对高信号图片 OCR 的整理和推断，适合放进 agent context。

## 统计

- instruction cards: 82
- docx media files: 98

## 指令类别

- Flow指令: 1
- Special Integer instruction: 8
- Transcendental Functions: 7
- Type conversion: 4
- double arith inst: 10
- float arith inst: 10
- half float arith inst: 12
- imm inst: 2
- int arith inst: 10
- logic inst: 7
- modify exception regs: 1
- unsigned int arith inst: 10

## Agent 使用建议

优先读取 `instruction_cards.jsonl` 中某个 mnemonic 的卡片；
如果问题涉及 SIMD128/SIMD32 尺度、4096bit operand 或 1024bit chunk 如何划分成 lane，先读 `OPERAND_LANE_MODEL.md`；
如果问题涉及 `LDM/STD/ILDMT/HSTT/COPYT`、`iter_exe_cond`、`base_addr[4]`、伪指令展开或 template 是否真的可运行，先读 `MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`；
需要更详细叙述时，再读取 `docx/dfu3500-simd-instruction-doc.md` 中对应章节。
如果该指令的关键解释藏在图片里，优先读取 `OCR_DERIVED_NOTES.md` 的对应小节；
只有字段仍不清楚时，再打开 `docx/media_ocr/raw/imageNN.txt` 或原图。
不要把整份 docx Markdown 一次塞进上下文。
