# my-writing-style

自进化的个人风格写作 skill：用你的声纹写微信公众号 / 知乎 / 技术社区文章，写完自动去 AI 味（写作与审查由两个隔离的子 agent 完成），并从你的定稿修改里持续学习、进化风格库。

## 安装

```bash
npx skills add MerliniKing/skills@my-writing-style
```

或手动复制本目录到 `~/.agents/skills/my-writing-style/`。

## 首次使用

1. 首次运行时 skill 会引导你把 `config.example.md` 复制为 `config.md`，选定两个数据目录（风格库 + 文章根目录），并自动创建目录、放入种子模板。
2. 把 3-10 篇你写的旧文章放进文章根目录的 `imported/`。
3. 对 agent 说：**「提炼我的风格」**。

## 口令

| 口令 | 作用 |
|------|------|
| 「帮我写篇公众号/知乎/掘金文章：题目」 | 写作子agent → 审查子agent 流水线，产出去 AI 味的初稿 |
| 「复盘这篇文章」+ 定稿 | 对比初稿与定稿，从你的修改提炼规则（确认后写入风格库） |
| 「提炼我的风格」/「重新提炼」 | 扫描语料重建画像；可重入，保留已学规则 |

## 设计原则

- **程序与数据分离**：技能只带流程和模板；你的风格库、文章住在你自己的工作仓里（git 版本化），本机配置 `config.md` 不入库。
- **写作与审查隔离**：写作者不看检查表（保持文气），审查者看不到写作过程（不带偏见），互相不可见。
- **只学"怎么写"，不学"写什么"**：AI 初稿（draft*.md）永远不进风格语料。

## 署名

`references/ai-tells-zh.md` 提炼自 [blader/humanizer](https://github.com/blader/humanizer)（MIT）与 Wikipedia [Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)。

## License

MIT
