# Knowledge spec (append to the library's CLAUDE.md)

> Appended automatically by book-eat Step 0 when the host library lacks a knowledge spec.

## 知识规格（不可违反，适用于一切写作）

- **来源标注**：一切知识标出处（**书+页** 或 **书+章节**；EPUB 合成页码每本固定可复现）
- Claude 通用知识而非已读书籍者标 **⚠未验证**，待书证后回填
- 主题笔记四件套：白话定义 → 出处 → `[[关联术语]]` → 易混辨析
- **典籍类书**（古籍点校本）→ 四层精注：①原典摘录 ②白话译文 ③考据（存疑标 ⚠）④义理；现代书 → 分级处理（核心精读/次要摘要/跳过）
- 复习卡片：Q/A + 出处 + 难度 1-5 + 状态
- 答疑中反复出现的盲点沉淀进 `faq/`
- **书籍档案**（`books/<书>/book-parse/`，GLM 直读逐页解析：文字全文+图/表 bbox）是页况与引文的真相源；引文一律从档案复制，档案没有的标 ⚠未验证

## 环境依赖

- PDF 渲染与扫描页处理用 pymupdf＋多模态直读（book_parse.py）；**不使用 OCR**
