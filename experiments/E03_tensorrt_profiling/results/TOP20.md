# E03：Top 20 执行层与详细元数据

运行 `20261021T080741Z_824b47`；原始包与 625 个文件 SHA256 已核对，以下由已回收原始文件在本机 CPU 重算。每模型每 artifact 三次独立 profile，显示各轮均值的平均；百分比的分母为该 artifact 的 layer profile 总和。

旧 Engine 只有 layer_names_only：内部 shape/dtype/tactic 不可得，因此时间表与新 detailed 元数据表分开。新 detailed 信息不代填旧 Engine。映射依据为层名/metadata 中的 model.N 和冻结模型定义，融合边界保留。CSV 保留完整执行层名、tensor 名、三次均值范围与实际 tactic。

### E01 原有 Engine

[完整 CSV](LEGACY_E01_baseline_top20.csv)。shape/dtype/tactic 为不可得，未从重建图代填。

| 排名 | YOLO 模块 | 执行层简称 | ms/batch2 | profile 占比 |
|---:|---|---|---:|---:|
| 1 | 3:Conv | L3/conv/Conv + SiLU | 0.87357 | 3.07% |
| 2 | 0:Conv | L0/act：SiLU（PWN） | 0.84674 | 2.97% |
| 3 | 2:C3k2 | L2/cv2/conv/Conv + SiLU | 0.82968 | 2.91% |
| 4 | 1:Conv | L1/conv/Conv + SiLU | 0.82775 | 2.91% |
| 5 | 5:Conv | L5/conv/Conv + SiLU | 0.81519 | 2.86% |
| 6 | 0:Conv | 输入 Reformat → L0 Conv | 0.65285 | 2.29% |
| 7 | 14:Upsample | L14/Resize_output_0 copy | 0.60870 | 2.14% |
| 8 | 16:C3k2 | L16/cv1/conv/Conv + SiLU | 0.56625 | 1.99% |
| 9 | 4:C3k2 | L4/cv2/conv/Conv + SiLU | 0.56446 | 1.98% |
| 10 | 10:C2PSA | L10/m/m.0/attn/Softmax | 0.53410 | 1.87% |
| 11 | 22:C3k2 | L22/m.0/m.0.1/attn/Softmax | 0.53381 | 1.87% |
| 12 | 0:Conv | L0/conv/Conv | 0.49951 | 1.75% |
| 13 | 2:C3k2 | L2/m.0/cv1/conv/Conv + SiLU | 0.46631 | 1.64% |
| 14 | 7:Conv | L7/conv/Conv + SiLU | 0.45701 | 1.60% |
| 15 | 2:C3k2 | L2/cv1/conv/Conv + SiLU | 0.43669 | 1.53% |
| 16 | 23:Detect | L23/cv2.0/cv2.0.0/conv/Conv + SiLU | 0.42579 | 1.49% |
| 17 | 2:C3k2 | L2/m.0/cv2：SiLU + Add（PWN） | 0.37324 | 1.31% |
| 18 | 13:C3k2 | L13/cv1/conv/Conv + SiLU | 0.36466 | 1.28% |
| 19 | 16:C3k2 | L16/cv2/conv/Conv + SiLU | 0.32155 | 1.13% |
| 20 | 2:C3k2 | L2/m.0/cv2/conv/Conv | 0.31985 | 1.12% |

Top20 合计 11.31770 ms，约占 39.73%。

### E02 原有 Engine

[完整 CSV](LEGACY_E02_c3k2_top20.csv)。shape/dtype/tactic 为不可得，未从重建图代填。

| 排名 | YOLO 模块 | 执行层简称 | ms/batch2 | profile 占比 |
|---:|---|---|---:|---:|
| 1 | 3:Conv | L3/conv/Conv + SiLU | 0.86439 | 3.03% |
| 2 | 0:Conv | L0/act：SiLU（PWN） | 0.84384 | 2.95% |
| 3 | 2:C3k2 | L2/cv2/conv/Conv + SiLU | 0.82578 | 2.89% |
| 4 | 1:Conv | L1/conv/Conv + SiLU | 0.81818 | 2.86% |
| 5 | 5:Conv | L5/conv/Conv + SiLU | 0.81577 | 2.86% |
| 6 | 0:Conv | 输入 Reformat → L0 Conv | 0.65390 | 2.29% |
| 7 | 14:Upsample | L14/Resize_output_0 copy | 0.60853 | 2.13% |
| 8 | 16:C3k2 | L16/cv1/conv/Conv + SiLU | 0.56619 | 1.98% |
| 9 | 4:C3k2 | L4/cv2/conv/Conv + SiLU | 0.56388 | 1.97% |
| 10 | 10:C2PSA | L10/m/m.0/attn/Softmax | 0.53399 | 1.87% |
| 11 | 22:C3k2 | L22/m.0/m.0.1/attn/Softmax | 0.53399 | 1.87% |
| 12 | 0:Conv | L0/conv/Conv | 0.49908 | 1.75% |
| 13 | 2:C3k2 | L2/m.0/cv1/conv/Conv + SiLU | 0.46769 | 1.64% |
| 14 | 7:Conv | L7/conv/Conv + SiLU | 0.45741 | 1.60% |
| 15 | 2:C3k2 | L2/cv1/conv/Conv + SiLU | 0.43554 | 1.52% |
| 16 | 23:Detect | L23/cv2.0/cv2.0.0/conv/Conv + SiLU | 0.42590 | 1.49% |
| 17 | 2:C3k2 | L2/m.0/cv2：SiLU + Add（PWN） | 0.37112 | 1.30% |
| 18 | 13:C3k2 | L13/cv1/conv/Conv + SiLU | 0.35869 | 1.26% |
| 19 | 2:C3k2 | L2/m.0/cv2/conv/Conv | 0.31975 | 1.12% |
| 20 | 16:C3k2 | L16/cv2/conv/Conv + SiLU | 0.31859 | 1.12% |

Top20 合计 11.28220 ms，约占 39.49%。

## E01 新 detailed Engine：实际 I/O、格式与 tactic

[完整 CSV](E01_baseline_top20.csv)，[L19 明细](E01_baseline_L19.csv)。下列 20/20 行均有实际输入输出与 tactic。维度按 Inspector 原样记录；物理布局以格式字典为准。多个输入以换行分隔。

| 排名 | YOLO / 节点简称 | TRT 类型 | mean ms | % | 输入 shape / 格式 | 输出 shape / 格式 | tactic |
|---:|---|---|---:|---:|---|---|---|
| 1 | 3:Conv<br>L3/conv/Conv + SiLU | CaskConvolution | 0.87137 | 3.07 | `2×128×160×160` F1 | `2×128×80×80` F1 | T01 |
| 2 | 0:Conv<br>L0/act：SiLU（PWN） | PointWiseV2 | 0.83183 | 2.93 | `2×32×320×320` F1 | `2×32×320×320` F1 | T02 |
| 3 | 2:C3k2<br>L2/cv2/conv/Conv + SiLU | CaskConvolution | 0.82760 | 2.91 | `2×96×160×160` F1 | `2×128×160×160` F1 | T03 |
| 4 | 5:Conv<br>L5/conv/Conv + SiLU | CaskConvolution | 0.82059 | 2.89 | `2×256×80×80` F1 | `2×256×40×40` F1 | T01 |
| 5 | 1:Conv<br>L1/conv/Conv + SiLU | CaskConvolution | 0.81871 | 2.88 | `2×32×320×320` F1 | `2×64×160×160` F1 | T04 |
| 6 | 0:Conv<br>输入 Reformat → L0 Conv | Reformat | 0.65274 | 2.30 | `2×3×640×640` F2 | `2×3×640×640` F3 | T05 |
| 7 | 14:Upsample<br>L14/Resize_output_0 copy | Reformat | 0.60827 | 2.14 | `2×256×80×80` F1 | `2×256×80×80` F1 | T05 |
| 8 | 16:C3k2<br>L16/cv1/conv/Conv + SiLU | CaskConvolution | 0.56682 | 1.99 | `2×512×80×80` F1 | `2×128×80×80` F1 | T06 |
| 9 | 4:C3k2<br>L4/cv2/conv/Conv + SiLU | CaskConvolution | 0.56075 | 1.97 | `2×192×80×80` F1 | `2×256×80×80` F1 | T07 |
| 10 | 10:C2PSA<br>L10/m/m.0/attn/Softmax | CudaSoftMax | 0.53386 | 1.88 | `2×4×400×400` F4 | `2×4×400×400` F4 | T08 |
| 11 | 22:C3k2<br>L22/m.0/m.0.1/attn/Softmax | CudaSoftMax | 0.53375 | 1.88 | `2×4×400×400` F4 | `2×4×400×400` F4 | T08 |
| 12 | 0:Conv<br>L0/conv/Conv | CaskConvolution | 0.49938 | 1.76 | `2×3×640×640` F3 | `2×32×320×320` F1 | T09 |
| 13 | 2:C3k2<br>L2/m.0/cv1/conv/Conv + SiLU | CaskConvolution | 0.46817 | 1.65 | `2×32×160×160` F1 | `2×16×160×160` F1 | T10 |
| 14 | 7:Conv<br>L7/conv/Conv + SiLU | CaskConvolution | 0.45972 | 1.62 | `2×256×40×40` F1 | `2×512×20×20` F1 | T11 |
| 15 | 2:C3k2<br>L2/cv1/conv/Conv + SiLU | CaskConvolution | 0.43697 | 1.54 | `2×64×160×160` F1 | `2×64×160×160` F1 | T12 |
| 16 | 23:Detect<br>L23/cv2.0/cv2.0.0/conv/Conv + SiLU | CaskConvolution | 0.42594 | 1.50 | `2×128×80×80` F1 | `2×32×80×80` F1 | T10 |
| 17 | 13:C3k2<br>L13/cv1/conv/Conv + SiLU | CaskConvolution | 0.36982 | 1.30 | `2×768×40×40` F1 | `2×256×40×40` F1 | T06 |
| 18 | 2:C3k2<br>L2/m.0/cv2：SiLU + Add（PWN） | PointWiseV2 | 0.36803 | 1.29 | `2×32×160×160` F1<br>`2×32×160×160` F1 | `2×32×160×160` F1 | T13 |
| 19 | 16:C3k2<br>L16/cv2/conv/Conv + SiLU | CaskConvolution | 0.32026 | 1.13 | `2×192×80×80` F1 | `2×128×80×80` F1 | T03 |
| 20 | 2:C3k2<br>L2/m.0/cv2/conv/Conv | CaskConvolution | 0.31978 | 1.12 | `2×16×160×160` F1 | `2×32×160×160` F1 | T14 |

## E02 新 detailed Engine：实际 I/O、格式与 tactic

[完整 CSV](E02_c3k2_top20.csv)，[L19 明细](E02_c3k2_L19.csv)。下列 20/20 行均有实际输入输出与 tactic。维度按 Inspector 原样记录；物理布局以格式字典为准。多个输入以换行分隔。

| 排名 | YOLO / 节点简称 | TRT 类型 | mean ms | % | 输入 shape / 格式 | 输出 shape / 格式 | tactic |
|---:|---|---|---:|---:|---|---|---|
| 1 | 3:Conv<br>L3/conv/Conv + SiLU | CaskConvolution | 0.87038 | 3.05 | `2×128×160×160` F1 | `2×128×80×80` F1 | T01 |
| 2 | 0:Conv<br>L0/act：SiLU（PWN） | PointWiseV2 | 0.83593 | 2.93 | `2×32×320×320` F1 | `2×32×320×320` F1 | T15 |
| 3 | 2:C3k2<br>L2/cv2/conv/Conv + SiLU | CaskConvolution | 0.82563 | 2.90 | `2×96×160×160` F1 | `2×128×160×160` F1 | T03 |
| 4 | 1:Conv<br>L1/conv/Conv + SiLU | CaskConvolution | 0.81494 | 2.86 | `2×32×320×320` F1 | `2×64×160×160` F1 | T04 |
| 5 | 5:Conv<br>L5/conv/Conv + SiLU | CaskConvolution | 0.81446 | 2.86 | `2×256×80×80` F1 | `2×256×40×40` F1 | T06 |
| 6 | 0:Conv<br>输入 Reformat → L0 Conv | Reformat | 0.65288 | 2.29 | `2×3×640×640` F2 | `2×3×640×640` F3 | T05 |
| 7 | 14:Upsample<br>L14/Resize_output_0 copy | Reformat | 0.60831 | 2.13 | `2×256×80×80` F1 | `2×256×80×80` F1 | T05 |
| 8 | 4:C3k2<br>L4/cv2/conv/Conv + SiLU | CaskConvolution | 0.56085 | 1.97 | `2×192×80×80` F1 | `2×256×80×80` F1 | T07 |
| 9 | 16:C3k2<br>L16/cv1/conv/Conv + SiLU | CaskConvolution | 0.55436 | 1.94 | `2×512×80×80` F1 | `2×128×80×80` F1 | T03 |
| 10 | 22:C3k2<br>L22/m.0/m.0.1/attn/Softmax | CudaSoftMax | 0.53395 | 1.87 | `2×4×400×400` F4 | `2×4×400×400` F4 | T08 |
| 11 | 10:C2PSA<br>L10/m/m.0/attn/Softmax | CudaSoftMax | 0.53392 | 1.87 | `2×4×400×400` F4 | `2×4×400×400` F4 | T08 |
| 12 | 0:Conv<br>L0/conv/Conv | CaskConvolution | 0.49872 | 1.75 | `2×3×640×640` F3 | `2×32×320×320` F1 | T09 |
| 13 | 2:C3k2<br>L2/m.0/cv1/conv/Conv + SiLU | CaskConvolution | 0.46824 | 1.64 | `2×32×160×160` F1 | `2×16×160×160` F1 | T10 |
| 14 | 7:Conv<br>L7/conv/Conv + SiLU | CaskConvolution | 0.46001 | 1.61 | `2×256×40×40` F1 | `2×512×20×20` F1 | T11 |
| 15 | 2:C3k2<br>L2/cv1/conv/Conv + SiLU | CaskConvolution | 0.43730 | 1.53 | `2×64×160×160` F1 | `2×64×160×160` F1 | T12 |
| 16 | 23:Detect<br>L23/cv2.0/cv2.0.0/conv/Conv + SiLU | CaskConvolution | 0.42622 | 1.49 | `2×128×80×80` F1 | `2×32×80×80` F1 | T10 |
| 17 | 2:C3k2<br>L2/m.0/cv2：SiLU + Add（PWN） | PointWiseV2 | 0.36927 | 1.30 | `2×32×160×160` F1<br>`2×32×160×160` F1 | `2×32×160×160` F1 | T13 |
| 18 | 13:C3k2<br>L13/cv1/conv/Conv + SiLU | CaskConvolution | 0.36151 | 1.27 | `2×768×40×40` F1 | `2×256×40×40` F1 | T16 |
| 19 | 16:C3k2<br>L16/cv2/conv/Conv + SiLU | CaskConvolution | 0.32193 | 1.13 | `2×192×80×80` F1 | `2×128×80×80` F1 | T07 |
| 20 | 2:C3k2<br>L2/m.0/cv2/conv/Conv | CaskConvolution | 0.31975 | 1.12 | `2×16×160×160` F1 | `2×32×160×160` F1 | T14 |

## 原始格式字典

- **F1**：`Channel major FP16 format where channel % 8 == 0`。
- **F2**：`Row major linear FP32`。
- **F3**：`Channel major FP16 format where channel % 4 == 0`。
- **F4**：`Row major linear FP16 format`。

## 原始 tactic 字典

T 编号仅为此文档的查表标识；下面保留 Inspector 的原始值。十六进制值按原样呈现，不解释为卷积 kernel 名。

**T01**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize128x128x32_stage4_warpsize2x2x1_g1_tensor16x8x16_t1r3s3_linkable
```

**T02**

```text
0x000000000000000e
```

**T03**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize128x128x32_stage4_warpsize2x2x1_g1_tensor16x8x16_simple_t1r1s1_linkable
```

**T04**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize256x64x32_stage3_warpsize4x1x1_g1_tensor16x8x16_t1r3s3_linkable
```

**T05**

```text
0x00000000000003ea
```

**T06**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize128x128x32_stage4_warpsize2x2x1_g1_tensor16x8x16_linkable
```

**T07**

```text
ampere_h1688cudnn_128x128_ldg8_relu_exp_interior_nhwc_linkable_tn_v1
```

**T08**

```text
0x00000000000003e9
```

**T09**

```text
sm80_xmma_fprop_image_first_layer_f16f16_f32_f16_nhwckrsc_nhwc_hmma_k32c4r3s3_stride2x2_tile16x64x32_tensor1688
```

**T10**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize128x32x32_stage4_warpsize4x1x1_g1_tensor16x8x16_t1r3s3_linkable
```

**T11**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize256x128x64_stage3_warpsize4x2x1_g1_tensor16x8x16_t1r3s3_linkable
```

**T12**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize256x64x32_stage3_warpsize4x1x1_g1_tensor16x8x16_simple_t1r1s1_linkable
```

**T13**

```text
0x000000000000001d
```

**T14**

```text
sm80_xmma_fprop_implicit_gemm_indexed_wo_smem_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize128x32x16_stage1_warpsize4x1x1_g1_tensor16x8x16_aligna8_alignc8
```

**T15**

```text
0x0000000000000011
```

**T16**

```text
sm80_xmma_fprop_implicit_gemm_f16f16_f16f16_f16_nhwckrsc_nhwc_tilesize128x128x32_stage4_warpsize2x2x1_g1_tensor16x8x16_t1r1s1_linkable
```

Tensor 名可能受融合与别名影响；CSV 记录 Inspector 的原文，不依据 tensor 名单独反推完整 PyTorch 拓扑。
