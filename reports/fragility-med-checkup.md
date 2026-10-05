# 判定稳健性报告 · 插件 `med-checkup`

> 探测方式：**取值范围内均匀取样** · 年龄 35 · 性别 male

---

# 判定稳健性报告

> **这个结论离临界值有多近？**
>
> 与召回/误报**完全分开统计**：脆弱项是风险提示，不是「AI 抄错了」。
> 这一类发现**不是注入的，是算出来的**——只有独立 oracle 能给出。
> 零模型调用、零成本、完全确定性。

**探测方式：取值范围内均匀取样**

取样是在**参考区间上下两倍的窄带里均匀**做的，所以它不受阈值位置影响。但它**仍然不等于真实报告分布**——真实分布要靠每个场景自己的样本生成器（那是内容插件的工作，见 `docs/15`）。**不要把这里的比例直接当成「真实报告的脆弱率」。**

## 总览

| 指标 | 数值 |
|---|---|
| 探测点 | 8000 |
| 判定会翻转的点 | **220** |
| **判定脆弱率** | **2.8%** |
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
| 丙氨酸氨基转移酶 | 49.987 U/L | normal | 往高偏 | mild | 0.1% |
| 丙氨酸氨基转移酶 | 49.9861 U/L | normal | 往高偏 | mild | 0.1% |
| 丙氨酸氨基转移酶 | 50.019 U/L | mild | 往低偏 | normal | 0.1% |
| 天门冬氨酸氨基转移酶 | 39.9988 U/L | normal | 往高偏 | mild | 0.1% |
| 肌酐 | 132.955 umol/L | mild | 往高偏 | marked | 0.1% |
| 肌酐 | 96.9394 umol/L | normal | 往高偏 | mild | 0.1% |
| 肌酐 | 96.9432 umol/L | normal | 往高偏 | mild | 0.1% |
| 肌酐 | 132.994 umol/L | mild | 往高偏 | marked | 0.1% |
| 肌酐 | 97.0914 umol/L | mild | 往低偏 | normal | 0.1% |
| 肌酐 | 132.924 umol/L | mild | 往高偏 | marked | 0.1% |
| 空腹血糖 | 6.10033 mmol/L | mild | 往低偏 | normal | 0.1% |
| γ-谷氨酰转移酶 | 59.9647 U/L | normal | 往高偏 | mild | 0.1% |
| 血红蛋白 | 110.061 g/L | mild | 往低偏 | marked | 0.1% |
| 血红蛋白 | 129.971 g/L | mild | 往高偏 | normal | 0.1% |
| 血红蛋白 | 109.945 g/L | marked | 往高偏 | mild | 0.1% |
| 总胆固醇 | 9.99672 mmol/L | marked | 往高偏 | critical | 0.1% |
| 总胆固醇 | 10.0075 mmol/L | critical | 往低偏 | marked | 0.1% |
| 总胆固醇 | 9.99597 mmol/L | marked | 往高偏 | critical | 0.1% |
| 总胆固醇 | 6.19432 mmol/L | mild | 往高偏 | marked | 0.1% |
| 总胆固醇 | 9.99569 mmol/L | marked | 往高偏 | critical | 0.1% |
| 总胆固醇 | 10.0015 mmol/L | critical | 往低偏 | marked | 0.1% |
| 尿酸 | 539.736 umol/L | mild | 往高偏 | marked | 0.1% |
| 尿酸 | 428.044 umol/L | mild | 往低偏 | normal | 0.1% |
| 尿酸 | 539.953 umol/L | mild | 往高偏 | marked | 0.1% |
| 丙氨酸氨基转移酶 | 49.9098 U/L | normal | 往高偏 | mild | 0.2% |
| 肌酐 | 132.824 umol/L | mild | 往高偏 | marked | 0.2% |
| 肌酐 | 132.821 umol/L | mild | 往高偏 | marked | 0.2% |
| 肌酐 | 96.8688 umol/L | normal | 往高偏 | mild | 0.2% |
| 空腹血糖 | 6.10945 mmol/L | mild | 往低偏 | normal | 0.2% |
| 空腹血糖 | 6.09295 mmol/L | normal | 往高偏 | mild | 0.2% |
| 空腹血糖 | 6.10677 mmol/L | mild | 往低偏 | normal | 0.2% |
| 空腹血糖 | 6.10947 mmol/L | mild | 往低偏 | normal | 0.2% |
| 空腹血糖 | 2.8032 mmol/L | mild | 往低偏 | critical | 0.2% |
| 空腹血糖 | 6.08971 mmol/L | normal | 往高偏 | mild | 0.2% |
| 空腹血糖 | 7.01032 mmol/L | marked | 往低偏 | mild | 0.2% |
| 空腹血糖 | 3.90495 mmol/L | normal | 往低偏 | mild | 0.2% |
| γ-谷氨酰转移酶 | 59.8994 U/L | normal | 往高偏 | mild | 0.2% |
| 血红蛋白 | 70.1336 g/L | marked | 往低偏 | critical | 0.2% |
| 血红蛋白 | 69.9037 g/L | critical | 往高偏 | marked | 0.2% |
| 血红蛋白 | 130.199 g/L | normal | 往低偏 | mild | 0.2% |
| 总胆固醇 | 9.98306 mmol/L | marked | 往高偏 | critical | 0.2% |
| 总胆固醇 | 10.0126 mmol/L | critical | 往低偏 | marked | 0.2% |
| 总胆固醇 | 10.0171 mmol/L | critical | 往低偏 | marked | 0.2% |
| 总胆固醇 | 5.18963 mmol/L | normal | 往高偏 | mild | 0.2% |
| 总胆固醇 | 10.0161 mmol/L | critical | 往低偏 | marked | 0.2% |
| 总胆固醇 | 9.98274 mmol/L | marked | 往高偏 | critical | 0.2% |
| 总胆固醇 | 6.18945 mmol/L | mild | 往高偏 | marked | 0.2% |
| 尿酸 | 428.666 umol/L | mild | 往低偏 | normal | 0.2% |
| 尿酸 | 540.858 umol/L | marked | 往低偏 | mild | 0.2% |
| 尿酸 | 540.675 umol/L | marked | 往低偏 | mild | 0.2% |
| 丙氨酸氨基转移酶 | 49.8247 U/L | normal | 往高偏 | mild | 0.5% |
| 天门冬氨酸氨基转移酶 | 40.1952 U/L | mild | 往低偏 | normal | 0.5% |
| 肌酐 | 96.5851 umol/L | normal | 往高偏 | mild | 0.5% |
| 肌酐 | 96.6985 umol/L | normal | 往高偏 | mild | 0.5% |
| 肌酐 | 96.632 umol/L | normal | 往高偏 | mild | 0.5% |
| 肌酐 | 133.473 umol/L | marked | 往低偏 | mild | 0.5% |
| 肌酐 | 133.57 umol/L | marked | 往低偏 | mild | 0.5% |
| 肌酐 | 96.5904 umol/L | normal | 往高偏 | mild | 0.5% |
| 肌酐 | 96.7309 umol/L | normal | 往高偏 | mild | 0.5% |
| 空腹血糖 | 7.0306 mmol/L | marked | 往低偏 | mild | 0.5% |
| 空腹血糖 | 6.1268 mmol/L | mild | 往低偏 | normal | 0.5% |
| 空腹血糖 | 3.9185 mmol/L | normal | 往低偏 | mild | 0.5% |
| 空腹血糖 | 2.79281 mmol/L | critical | 往高偏 | mild | 0.5% |
| 空腹血糖 | 7.02558 mmol/L | marked | 往低偏 | mild | 0.5% |
| 空腹血糖 | 6.08359 mmol/L | normal | 往高偏 | mild | 0.5% |
| 空腹血糖 | 2.78913 mmol/L | critical | 往高偏 | mild | 0.5% |
| 空腹血糖 | 6.97934 mmol/L | mild | 往高偏 | marked | 0.5% |
| 空腹血糖 | 2.79387 mmol/L | critical | 往高偏 | mild | 0.5% |
| 空腹血糖 | 7.01972 mmol/L | marked | 往低偏 | mild | 0.5% |
| 空腹血糖 | 3.91794 mmol/L | normal | 往低偏 | mild | 0.5% |
| 空腹血糖 | 6.11704 mmol/L | mild | 往低偏 | normal | 0.5% |
| 空腹血糖 | 2.80656 mmol/L | mild | 往低偏 | critical | 0.5% |
| 空腹血糖 | 3.9128 mmol/L | normal | 往低偏 | mild | 0.5% |
| 空腹血糖 | 6.12829 mmol/L | mild | 往低偏 | normal | 0.5% |
| γ-谷氨酰转移酶 | 59.8316 U/L | normal | 往高偏 | mild | 0.5% |
| γ-谷氨酰转移酶 | 59.8331 U/L | normal | 往高偏 | mild | 0.5% |
| 血红蛋白 | 130.446 g/L | normal | 往低偏 | mild | 0.5% |
| 血红蛋白 | 129.514 g/L | mild | 往高偏 | normal | 0.5% |
| 血红蛋白 | 109.498 g/L | marked | 往高偏 | mild | 0.5% |
| 血红蛋白 | 69.7869 g/L | critical | 往高偏 | marked | 0.5% |
| 血红蛋白 | 69.7929 g/L | critical | 往高偏 | marked | 0.5% |
| 血红蛋白 | 69.6743 g/L | critical | 往高偏 | marked | 0.5% |
| 血红蛋白 | 109.548 g/L | marked | 往高偏 | mild | 0.5% |
| 血红蛋白 | 129.682 g/L | mild | 往高偏 | normal | 0.5% |
| 血红蛋白 | 110.483 g/L | mild | 往低偏 | marked | 0.5% |
| 血红蛋白 | 69.827 g/L | critical | 往高偏 | marked | 0.5% |
| 血红蛋白 | 130.573 g/L | normal | 往低偏 | mild | 0.5% |
| 血红蛋白 | 130.505 g/L | normal | 往低偏 | mild | 0.5% |
| 血红蛋白 | 110.408 g/L | mild | 往低偏 | marked | 0.5% |
| 血红蛋白 | 110.302 g/L | mild | 往低偏 | marked | 0.5% |
| 总胆固醇 | 6.17819 mmol/L | mild | 往高偏 | marked | 0.5% |
| 总胆固醇 | 9.96803 mmol/L | marked | 往高偏 | critical | 0.5% |
| 总胆固醇 | 9.95884 mmol/L | marked | 往高偏 | critical | 0.5% |
| 总胆固醇 | 9.97304 mmol/L | marked | 往高偏 | critical | 0.5% |
| 总胆固醇 | 10.0229 mmol/L | critical | 往低偏 | marked | 0.5% |
| 总胆固醇 | 10.0369 mmol/L | critical | 往低偏 | marked | 0.5% |
| 总胆固醇 | 5.17789 mmol/L | normal | 往高偏 | mild | 0.5% |
| 总胆固醇 | 6.17554 mmol/L | mild | 往高偏 | marked | 0.5% |
| 总胆固醇 | 10.0223 mmol/L | critical | 往低偏 | marked | 0.5% |
| 总胆固醇 | 6.17171 mmol/L | mild | 往高偏 | marked | 0.5% |
| 总胆固醇 | 5.21062 mmol/L | mild | 往低偏 | normal | 0.5% |
| 尿酸 | 541.141 umol/L | marked | 往低偏 | mild | 0.5% |
| 尿酸 | 537.344 umol/L | mild | 往高偏 | marked | 0.5% |
| 尿酸 | 537.553 umol/L | mild | 往高偏 | marked | 0.5% |
| 尿酸 | 430.002 umol/L | mild | 往低偏 | normal | 0.5% |
| 尿酸 | 538.557 umol/L | mild | 往高偏 | marked | 0.5% |
| 尿酸 | 538.521 umol/L | mild | 往高偏 | marked | 0.5% |
| 尿酸 | 542.361 umol/L | marked | 往低偏 | mild | 0.5% |
| 尿酸 | 429.762 umol/L | mild | 往低偏 | normal | 0.5% |
| 尿酸 | 537.636 umol/L | mild | 往高偏 | marked | 0.5% |
| 尿酸 | 426.934 umol/L | normal | 往高偏 | mild | 0.5% |
| 尿酸 | 429.548 umol/L | mild | 往低偏 | normal | 0.5% |
| 丙氨酸氨基转移酶 | 49.6238 U/L | normal | 往高偏 | mild | 1.0% |
| 丙氨酸氨基转移酶 | 50.4961 U/L | mild | 往低偏 | normal | 1.0% |
| 丙氨酸氨基转移酶 | 49.5827 U/L | normal | 往高偏 | mild | 1.0% |
| 天门冬氨酸氨基转移酶 | 39.6447 U/L | normal | 往高偏 | mild | 1.0% |
| 天门冬氨酸氨基转移酶 | 39.7779 U/L | normal | 往高偏 | mild | 1.0% |
| 天门冬氨酸氨基转移酶 | 40.3647 U/L | mild | 往低偏 | normal | 1.0% |
| 天门冬氨酸氨基转移酶 | 40.2813 U/L | mild | 往低偏 | normal | 1.0% |
| 天门冬氨酸氨基转移酶 | 39.7264 U/L | normal | 往高偏 | mild | 1.0% |
| 天门冬氨酸氨基转移酶 | 39.7451 U/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 96.1608 umol/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 96.1761 umol/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 131.847 umol/L | mild | 往高偏 | marked | 1.0% |
| 肌酐 | 96.3157 umol/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 131.898 umol/L | mild | 往高偏 | marked | 1.0% |
| 肌酐 | 131.782 umol/L | mild | 往高偏 | marked | 1.0% |
| 肌酐 | 131.995 umol/L | mild | 往高偏 | marked | 1.0% |
| 肌酐 | 96.1363 umol/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 134.333 umol/L | marked | 往低偏 | mild | 1.0% |
| 肌酐 | 96.1305 umol/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 96.2426 umol/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 133.807 umol/L | marked | 往低偏 | mild | 1.0% |
| 肌酐 | 133.903 umol/L | marked | 往低偏 | mild | 1.0% |
| 肌酐 | 96.484 umol/L | normal | 往高偏 | mild | 1.0% |
| 肌酐 | 131.688 umol/L | mild | 往高偏 | marked | 1.0% |
| 肌酐 | 131.966 umol/L | mild | 往高偏 | marked | 1.0% |
| 肌酐 | 133.932 umol/L | marked | 往低偏 | mild | 1.0% |
| 肌酐 | 132.008 umol/L | mild | 往高偏 | marked | 1.0% |
| 肌酐 | 131.696 umol/L | mild | 往高偏 | marked | 1.0% |
| 空腹血糖 | 2.77237 mmol/L | critical | 往高偏 | mild | 1.0% |
| 空腹血糖 | 6.04102 mmol/L | normal | 往高偏 | mild | 1.0% |
| 空腹血糖 | 3.86428 mmol/L | mild | 往高偏 | normal | 1.0% |
| 空腹血糖 | 7.03524 mmol/L | marked | 往低偏 | mild | 1.0% |
| 空腹血糖 | 6.93208 mmol/L | mild | 往高偏 | marked | 1.0% |
| 空腹血糖 | 7.05289 mmol/L | marked | 往低偏 | mild | 1.0% |
| 空腹血糖 | 6.13797 mmol/L | mild | 往低偏 | normal | 1.0% |
| 空腹血糖 | 6.15729 mmol/L | mild | 往低偏 | normal | 1.0% |
| 空腹血糖 | 6.05456 mmol/L | normal | 往高偏 | mild | 1.0% |
| 空腹血糖 | 6.04081 mmol/L | normal | 往高偏 | mild | 1.0% |
| 空腹血糖 | 7.05251 mmol/L | marked | 往低偏 | mild | 1.0% |
| 空腹血糖 | 6.16102 mmol/L | mild | 往低偏 | normal | 1.0% |
| 空腹血糖 | 6.06289 mmol/L | normal | 往高偏 | mild | 1.0% |
| 空腹血糖 | 2.77337 mmol/L | critical | 往高偏 | mild | 1.0% |
| 空腹血糖 | 6.94821 mmol/L | mild | 往高偏 | marked | 1.0% |
| 空腹血糖 | 7.04307 mmol/L | marked | 往低偏 | mild | 1.0% |
| 空腹血糖 | 2.8271 mmol/L | mild | 往低偏 | critical | 1.0% |
| 空腹血糖 | 6.06512 mmol/L | normal | 往高偏 | mild | 1.0% |
| 空腹血糖 | 6.95104 mmol/L | mild | 往高偏 | marked | 1.0% |
| 空腹血糖 | 7.04084 mmol/L | marked | 往低偏 | mild | 1.0% |
| 空腹血糖 | 3.93462 mmol/L | normal | 往低偏 | mild | 1.0% |
| 空腹血糖 | 7.06896 mmol/L | marked | 往低偏 | mild | 1.0% |
| 空腹血糖 | 6.05304 mmol/L | normal | 往高偏 | mild | 1.0% |
| 空腹血糖 | 6.04994 mmol/L | normal | 往高偏 | mild | 1.0% |
| γ-谷氨酰转移酶 | 59.452 U/L | normal | 往高偏 | mild | 1.0% |
| γ-谷氨酰转移酶 | 59.6641 U/L | normal | 往高偏 | mild | 1.0% |
| γ-谷氨酰转移酶 | 60.4164 U/L | mild | 往低偏 | normal | 1.0% |
| γ-谷氨酰转移酶 | 59.5039 U/L | normal | 往高偏 | mild | 1.0% |
| γ-谷氨酰转移酶 | 59.613 U/L | normal | 往高偏 | mild | 1.0% |
| 血红蛋白 | 110.601 g/L | mild | 往低偏 | marked | 1.0% |
| 血红蛋白 | 110.887 g/L | mild | 往低偏 | marked | 1.0% |
| 血红蛋白 | 131.292 g/L | normal | 往低偏 | mild | 1.0% |
| 血红蛋白 | 69.3596 g/L | critical | 往高偏 | marked | 1.0% |
| 血红蛋白 | 70.6941 g/L | marked | 往低偏 | critical | 1.0% |
| 血红蛋白 | 130.825 g/L | normal | 往低偏 | mild | 1.0% |
| 血红蛋白 | 69.3998 g/L | critical | 往高偏 | marked | 1.0% |
| 血红蛋白 | 110.658 g/L | mild | 往低偏 | marked | 1.0% |
| 血红蛋白 | 129.221 g/L | mild | 往高偏 | normal | 1.0% |
| 血红蛋白 | 131.094 g/L | normal | 往低偏 | mild | 1.0% |
| 血红蛋白 | 129.123 g/L | mild | 往高偏 | normal | 1.0% |
| 血红蛋白 | 131.029 g/L | normal | 往低偏 | mild | 1.0% |
| 血红蛋白 | 69.3231 g/L | critical | 往高偏 | marked | 1.0% |
| 血红蛋白 | 129.263 g/L | mild | 往高偏 | normal | 1.0% |
| 血红蛋白 | 70.3894 g/L | marked | 往低偏 | critical | 1.0% |
| 血红蛋白 | 129.093 g/L | mild | 往高偏 | normal | 1.0% |
| 血红蛋白 | 108.955 g/L | marked | 往高偏 | mild | 1.0% |
| 血红蛋白 | 131.065 g/L | normal | 往低偏 | mild | 1.0% |
| 总胆固醇 | 9.92638 mmol/L | marked | 往高偏 | critical | 1.0% |
| 总胆固醇 | 9.9385 mmol/L | marked | 往高偏 | critical | 1.0% |
| 总胆固醇 | 5.23771 mmol/L | mild | 往低偏 | normal | 1.0% |
| 总胆固醇 | 6.25753 mmol/L | marked | 往低偏 | mild | 1.0% |
| 总胆固醇 | 5.15941 mmol/L | normal | 往高偏 | mild | 1.0% |
| 总胆固醇 | 10.0535 mmol/L | critical | 往低偏 | marked | 1.0% |
| 总胆固醇 | 10.0651 mmol/L | critical | 往低偏 | marked | 1.0% |
| 总胆固醇 | 9.90378 mmol/L | marked | 往高偏 | critical | 1.0% |
| 总胆固醇 | 10.0862 mmol/L | critical | 往低偏 | marked | 1.0% |
| 总胆固醇 | 6.15334 mmol/L | mild | 往高偏 | marked | 1.0% |
| 总胆固醇 | 5.16064 mmol/L | normal | 往高偏 | mild | 1.0% |
| 总胆固醇 | 9.90837 mmol/L | marked | 往高偏 | critical | 1.0% |
| 总胆固醇 | 5.24945 mmol/L | mild | 往低偏 | normal | 1.0% |
| 总胆固醇 | 9.93896 mmol/L | marked | 往高偏 | critical | 1.0% |
| 总胆固醇 | 10.076 mmol/L | critical | 往低偏 | marked | 1.0% |
| 总胆固醇 | 10.0646 mmol/L | critical | 往低偏 | marked | 1.0% |
| 总胆固醇 | 9.90897 mmol/L | marked | 往高偏 | critical | 1.0% |
| 尿酸 | 535.719 umol/L | mild | 往高偏 | marked | 1.0% |
| 尿酸 | 543.389 umol/L | marked | 往低偏 | mild | 1.0% |
| 尿酸 | 543.011 umol/L | marked | 往低偏 | mild | 1.0% |
| 尿酸 | 431.068 umol/L | mild | 往低偏 | normal | 1.0% |
| 尿酸 | 536.972 umol/L | mild | 往高偏 | marked | 1.0% |
| 尿酸 | 431.152 umol/L | mild | 往低偏 | normal | 1.0% |
| 尿酸 | 432.201 umol/L | mild | 往低偏 | normal | 1.0% |
| 尿酸 | 545.401 umol/L | marked | 往低偏 | mild | 1.0% |
| 尿酸 | 543.766 umol/L | marked | 往低偏 | mild | 1.0% |
| 尿酸 | 535.881 umol/L | mild | 往高偏 | marked | 1.0% |
| 尿酸 | 430.414 umol/L | mild | 往低偏 | normal | 1.0% |
| 尿酸 | 430.251 umol/L | mild | 往低偏 | normal | 1.0% |
| 尿酸 | 424.919 umol/L | normal | 往高偏 | mild | 1.0% |
| 尿酸 | 535.234 umol/L | mild | 往高偏 | marked | 1.0% |
| 尿酸 | 543.144 umol/L | marked | 往低偏 | mild | 1.0% |
| 尿酸 | 424.043 umol/L | normal | 往高偏 | mild | 1.0% |

## 怎么用这个数字

- **对用户**：离临界值越近，越应当给「单次结果仅供参考、建议复查」的措辞，
  而不是给一个硬结论。
- **对产线**：脆弱率高的指标说明它的参考区间与结论口径**过于敏感**，
  需要复核阈值设定或提高测量精度。
- **对评测**：它和召回率**互不替代**。召回率问「有没有漏掉错」，
  它问「结论有多硬」。

> ⚠️ 脆弱项**算不算缺陷**是产品判断（见 `docs/02-metrics.md`）。
> 本报告只给事实，不替你下结论。
