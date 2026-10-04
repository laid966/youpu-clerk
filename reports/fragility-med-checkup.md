# 判定稳健性报告 · 插件 `med-checkup`

> 探测方式：**阈值附近扫描** · 年龄 35 · 性别 male

---

# 判定稳健性报告

> **这个结论离临界值有多近？**
>
> 与召回/误报**完全分开统计**：脆弱项是风险提示，不是「AI 抄错了」。
> 这一类发现**不是注入的，是算出来的**——只有独立 oracle 能给出。
> 零模型调用、零成本、完全确定性。

**探测方式：阈值附近扫描**

⚠️ **探测点是刻意放在判定阈值上的**，所以这个比例必然偏高——它度量的是「**每个阈值有多敏感**」，用来复核阈值设定；**不能读成「真实报告里有多少结论是脆的」**。要看后者，请用 `--mode uniform`（范围内均匀取样）或 `--artifact`（扫一份真实产物）。

## 总览

| 指标 | 数值 |
|---|---|
| 探测点 | 114 |
| 判定会翻转的点 | **75** |
| **判定脆弱率** | **65.8%** |
| 其中紧贴临界值（偏差 ≤0.2%） | 50 |
| 判定所用的误差量级 | ±1.00% |

## 没算出来的部分（显式列出，不静默跳过）

| 原因 | 探测点 |
|---|---|
| 域里没有这个指标的阈值 | 0 |
| 扰动会越出域声明的取值范围 | 0 |
| 判定落在「缺事实转人工」 | 0 |

## 脆弱的判定（按离临界值的距离排序）

| 指标 | 当前值 | 当前判定 | 方向 | 会翻转成 | 需要多小的偏差 |
|---|---|---|---|---|---|
| 丙氨酸氨基转移酶 | 50 U/L | normal | 往高偏 | mild | 0.1% |
| 丙氨酸氨基转移酶 | 120 U/L | mild | 往高偏 | marked | 0.1% |
| 丙氨酸氨基转移酶 | 300 U/L | marked | 往高偏 | critical | 0.1% |
| 天门冬氨酸氨基转移酶 | 40 U/L | normal | 往高偏 | mild | 0.1% |
| 天门冬氨酸氨基转移酶 | 100 U/L | mild | 往高偏 | marked | 0.1% |
| 天门冬氨酸氨基转移酶 | 300 U/L | marked | 往高偏 | critical | 0.1% |
| 肌酐 | 97 umol/L | normal | 往高偏 | mild | 0.1% |
| 肌酐 | 133 umol/L | mild | 往高偏 | marked | 0.1% |
| 肌酐 | 450 umol/L | marked | 往高偏 | critical | 0.1% |
| 空腹血糖 | 2.8 mmol/L | mild | 往低偏 | critical | 0.1% |
| 空腹血糖 | 3.9 mmol/L | normal | 往低偏 | mild | 0.1% |
| 空腹血糖 | 6.1 mmol/L | normal | 往高偏 | mild | 0.1% |
| 空腹血糖 | 7 mmol/L | mild | 往高偏 | marked | 0.1% |
| 空腹血糖 | 13.9 mmol/L | marked | 往高偏 | critical | 0.1% |
| γ-谷氨酰转移酶 | 60 U/L | normal | 往高偏 | mild | 0.1% |
| γ-谷氨酰转移酶 | 180 U/L | mild | 往高偏 | marked | 0.1% |
| γ-谷氨酰转移酶 | 600 U/L | marked | 往高偏 | critical | 0.1% |
| 血红蛋白 | 70 g/L | marked | 往低偏 | critical | 0.1% |
| 血红蛋白 | 110 g/L | mild | 往低偏 | marked | 0.1% |
| 血红蛋白 | 130 g/L | normal | 往低偏 | mild | 0.1% |
| 总胆固醇 | 5.2 mmol/L | normal | 往高偏 | mild | 0.1% |
| 总胆固醇 | 6.2 mmol/L | mild | 往高偏 | marked | 0.1% |
| 总胆固醇 | 10 mmol/L | marked | 往高偏 | critical | 0.1% |
| 尿酸 | 428 umol/L | normal | 往高偏 | mild | 0.1% |
| 尿酸 | 540 umol/L | mild | 往高偏 | marked | 0.1% |
| 丙氨酸氨基转移酶 | 50.1 U/L | mild | 往低偏 | normal | 0.2% |
| 丙氨酸氨基转移酶 | 120.24 U/L | marked | 往低偏 | mild | 0.2% |
| 丙氨酸氨基转移酶 | 300.6 U/L | critical | 往低偏 | marked | 0.2% |
| 天门冬氨酸氨基转移酶 | 40.08 U/L | mild | 往低偏 | normal | 0.2% |
| 天门冬氨酸氨基转移酶 | 100.2 U/L | marked | 往低偏 | mild | 0.2% |
| 天门冬氨酸氨基转移酶 | 300.6 U/L | critical | 往低偏 | marked | 0.2% |
| 肌酐 | 97.194 umol/L | mild | 往低偏 | normal | 0.2% |
| 肌酐 | 133.266 umol/L | marked | 往低偏 | mild | 0.2% |
| 肌酐 | 450.9 umol/L | critical | 往低偏 | marked | 0.2% |
| 空腹血糖 | 2.8056 mmol/L | mild | 往低偏 | critical | 0.2% |
| 空腹血糖 | 3.9078 mmol/L | normal | 往低偏 | mild | 0.2% |
| 空腹血糖 | 6.1122 mmol/L | mild | 往低偏 | normal | 0.2% |
| 空腹血糖 | 7.014 mmol/L | marked | 往低偏 | mild | 0.2% |
| 空腹血糖 | 13.9278 mmol/L | critical | 往低偏 | marked | 0.2% |
| γ-谷氨酰转移酶 | 60.12 U/L | mild | 往低偏 | normal | 0.2% |
| γ-谷氨酰转移酶 | 180.36 U/L | marked | 往低偏 | mild | 0.2% |
| γ-谷氨酰转移酶 | 601.2 U/L | critical | 往低偏 | marked | 0.2% |
| 血红蛋白 | 70.14 g/L | marked | 往低偏 | critical | 0.2% |
| 血红蛋白 | 110.22 g/L | mild | 往低偏 | marked | 0.2% |
| 血红蛋白 | 130.26 g/L | normal | 往低偏 | mild | 0.2% |
| 总胆固醇 | 5.2104 mmol/L | mild | 往低偏 | normal | 0.2% |
| 总胆固醇 | 6.2124 mmol/L | marked | 往低偏 | mild | 0.2% |
| 总胆固醇 | 10.02 mmol/L | critical | 往低偏 | marked | 0.2% |
| 尿酸 | 428.856 umol/L | mild | 往低偏 | normal | 0.2% |
| 尿酸 | 541.08 umol/L | marked | 往低偏 | mild | 0.2% |
| 丙氨酸氨基转移酶 | 49.9 U/L | normal | 往高偏 | mild | 0.5% |
| 丙氨酸氨基转移酶 | 119.76 U/L | mild | 往高偏 | marked | 0.5% |
| 丙氨酸氨基转移酶 | 299.4 U/L | marked | 往高偏 | critical | 0.5% |
| 天门冬氨酸氨基转移酶 | 39.92 U/L | normal | 往高偏 | mild | 0.5% |
| 天门冬氨酸氨基转移酶 | 99.8 U/L | mild | 往高偏 | marked | 0.5% |
| 天门冬氨酸氨基转移酶 | 299.4 U/L | marked | 往高偏 | critical | 0.5% |
| 肌酐 | 96.806 umol/L | normal | 往高偏 | mild | 0.5% |
| 肌酐 | 132.734 umol/L | mild | 往高偏 | marked | 0.5% |
| 肌酐 | 449.1 umol/L | marked | 往高偏 | critical | 0.5% |
| 空腹血糖 | 2.7944 mmol/L | critical | 往高偏 | mild | 0.5% |
| 空腹血糖 | 3.8922 mmol/L | mild | 往高偏 | normal | 0.5% |
| 空腹血糖 | 6.0878 mmol/L | normal | 往高偏 | mild | 0.5% |
| 空腹血糖 | 6.986 mmol/L | mild | 往高偏 | marked | 0.5% |
| 空腹血糖 | 13.8722 mmol/L | marked | 往高偏 | critical | 0.5% |
| γ-谷氨酰转移酶 | 59.88 U/L | normal | 往高偏 | mild | 0.5% |
| γ-谷氨酰转移酶 | 179.64 U/L | mild | 往高偏 | marked | 0.5% |
| γ-谷氨酰转移酶 | 598.8 U/L | marked | 往高偏 | critical | 0.5% |
| 血红蛋白 | 69.86 g/L | critical | 往高偏 | marked | 0.5% |
| 血红蛋白 | 109.78 g/L | marked | 往高偏 | mild | 0.5% |
| 血红蛋白 | 129.74 g/L | mild | 往高偏 | normal | 0.5% |
| 总胆固醇 | 5.1896 mmol/L | normal | 往高偏 | mild | 0.5% |
| 总胆固醇 | 6.1876 mmol/L | mild | 往高偏 | marked | 0.5% |
| 总胆固醇 | 9.98 mmol/L | marked | 往高偏 | critical | 0.5% |
| 尿酸 | 427.144 umol/L | normal | 往高偏 | mild | 0.5% |
| 尿酸 | 538.92 umol/L | mild | 往高偏 | marked | 0.5% |

## 怎么用这个数字

- **对用户**：离临界值越近，越应当给「单次结果仅供参考、建议复查」的措辞，
  而不是给一个硬结论。
- **对产线**：脆弱率高的指标说明它的参考区间与结论口径**过于敏感**，
  需要复核阈值设定或提高测量精度。
- **对评测**：它和召回率**互不替代**。召回率问「有没有漏掉错」，
  它问「结论有多硬」。

> ⚠️ 脆弱项**算不算缺陷**是产品判断（见 `docs/02-metrics.md`）。
> 本报告只给事实，不替你下结论。
