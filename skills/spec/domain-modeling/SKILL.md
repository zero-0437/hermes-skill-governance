---
name: domain-modeling
description: 构建和精炼项目的领域模型 — 挑战术语、细化定义、记录架构决策。与 spec-authoring 配合，在 PRD 产出前/同时建立共享语言
---

# Domain Modeling

> 来源：mattpocock/skills domain-modeling（经 Hermes 多 Agent 架构适配）

## 定位

在项目启动阶段**主动构建领域模型**。不是被动读 CONTEXT.md（那是所有技能都能做的习惯），而是在需求对齐过程中**挑战术语边界、发明极端场景、当场写下游汇表和决策**。

设计哲学：一次配置，全局受益。CONTEXT.md 产出后，后续所有委派 programmer 时注入其路径，subagent 直接消费领域词表，无需重复对齐。

---

## 产出物

产出到 `.shared/{task_id}/` 目录：

```
.shared/{task_id}/
├── PRD.md            （与 spec-authoring 协作产出）
├── CONTEXT.md        （领域词表 — 本次新增）
└── docs/adr/         （架构决策记录 — 本次新增）
    └── 0001-xxx.md
```

### CONTEXT.md 规则

- 仅存放术语定义。不含实现细节、不含规范、不含草稿
- 每条术语一行，格式：`术语：定义（一句话）`
- 反对称关系也记录：`取消 ≠ 退款 — 取消订单不触发退款`

### ADR 规则

仅在**全部满足以下三条件**时才写 ADR：

1. **难撤销** — 改主意成本大
2. **无上下文会困惑** — 后续开发者看到会说「为什么这么搞？」
3. **有真实权衡** — 存在真正可替代方案，你选了其一

缺任一条件就跳过。ADR 用标准格式：Context → Decision → Consequences。

---

## 工作流程

### 时机

在 spec-agent 的**第二次委派**（用户已回答所有 NEEDS_CONTEXT 问题后）执行，与 `spec-authoring` 并行或穿插：

```
第一次委派：NEEDS_CONTEXT（抛出所有问题，不含领域建模）
第二次委派：domain-modeling + spec-authoring（同时产出 CONTEXT.md + ADRs + PRD）
```

### 步骤

#### Step 1 — 识别关键术语

从用户回答和任务描述中提取所有业务概念。对每个概念问：

- 这是用户视角的角色（User/Customer/Admin）还是系统实体（Order/Payment）？
- 这些术语之间是包含关系（User has Orders）还是等价关系（Customer = User）？
- 是否存在模糊或同义反复的术语？

#### Step 2 — 挑战模糊语言

当用户使用以下类型表述时，不能接受模糊，必须精确定义：

| 模糊表述 | 处理方式 |
|---------|---------|
| 「用户」 | 指 Customer 还是 Admin？还是广义访客？ |
| 「账户」 | 指登录凭证还是余额账户？还是两个意思？ |
| 「订单」 | 下单即创建，还是支付后才创建？ |
| 「取消」 | 取消订单 = 退款？取消订阅 = 冻结？ |
| 「已处理」 | 已创建？已支付？已发货？已到货？ |

记录到 `CONTEXT.md`，注明分辨原因。

#### Step 3 — 用极端场景考验边界

对已定义的术语关系，发明极端场景测试：

> 术语：Order 包含 LineItem，LineItem 有 price 和 quantity
> 场景：「如果下单后 price 变了，已存在的 LineItem 价格变不变？」
> 结果：需要区分「下单时锁定价格」和「实时跟随价格」→ 细化到 CONTEXT.md

#### Step 4 — 交叉验证（仅当 spec-agent 能读仓库）

如果项目已有代码：

- 检查代码中的变量/函数/模块命名是否与 CONTEXT.md 一致
- 不一致时记录分歧，在 PRD 的 Implementation Decisions 中标注

如果无代码，跳过此步。

#### Step 5 — 写入 CONTEXT.md

每决议一条术语，立即写入。格式：

```markdown
# 领域词表

## 核心实体

- **User**：系统的登录用户，区别于 Customer（消费方）。一个 User 可以管理多个 Customer。
- **Customer**：实际消费服务的客户。由 User 创建和管理。

## 关键分辨

- **取消 ≠ 退款**：取消订单后不自动触发退款，退款是独立操作。
- **订阅 ≠ 套餐**：订阅是计费周期概念，套餐是权限集合。
```

#### Step 6 — 选择性写 ADR

仅在满足前述三条件时创建 ADR。文件命名为 `docs/adr/0001-标题.md`，内容用标准格式：

```markdown
# ADR-0001：使用事件溯源存储订单

## 上下文
订单状态变化频繁且需要审计追踪。

## 决策
采用事件溯源（Event Sourcing），而非传统 CRUD。

## 原因
审计需求 + 需要重建任意时间点的订单快照。

## 后果
- 查询需要聚合事件，引入 read model
- 学习曲线增加
```

---

## 边界

| 做 | 不做 |
|---|------|
| 精炼术语，写入 CONTEXT.md | 修改 .py/.js/.yaml 文件（那是 programmer 的职责） |
| 提出需要区分的场景问题（以 [DOMAIN-Q] 标记） | 运行测试或构建命令 |
| 在 PRD 中引用 CONTEXT.md 中定义的术语 | 将 CONTEXT.md 当作规范或草稿使用 |
| 必要时写 ADR | 为每个决策都写 ADR |

---

## 质量检查清单

产出前自查：

- [ ] 每个术语是否都有精确定义（无歧义）？
- [ ] 模糊词是否已被特定词替代？
- [ ] 术语关系是否通过极端场景验证过？
- [ ] CONTEXT.md 是否不含实现细节？
- [ ] ADR 是否满足三条件才写？
- [ ] 命名是否统一（PRD 中的术语与 CONTEXT.md 一致）？
