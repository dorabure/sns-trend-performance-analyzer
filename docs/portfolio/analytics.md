# Analytics: NULL / Trend / Gap

[README](../../README.md) · [Architecture](architecture.md)

## 不明値と実値0

NULLは「観測できない / 計算できない」、0は「観測した結果0」です。画面ではNULLを「—」で表示します。Engagementはlikes + comments + shares + savesの既知値の合計で、全項目NULLなら不明です。不明投稿も投稿数に含め、平均の分母からは除きます。投稿指標は各投稿の最新recorded_at Snapshotを使います。Followersを複数Accountで合算せず、Engagement Rateを異なるSNS・分母間で混ぜません。

## Trend Score

MARKET投稿をProject別・SNS別・Topic / Term別に集計します。基準日DのCurrentはD−6〜D、PreviousはD−13〜D−7、PriorはD−20〜D−14（UTC・両端含む各7日）。選択した90日全体のScoreではなく、各日を終点とする7日Rolling Scoreです。

| Component | 元の値 | Weight |
| --- | --- | --- |
| Post Growth | (Current投稿数 − Previous投稿数) / Previous投稿数 × 100 | 40% |
| Engagement Growth | (Current合計Engagement − Previous合計Engagement) / Previous合計Engagement × 100 | 30% |
| Engagement Level | Current合計Engagement / Engagement既知投稿数 | 20% |
| Acceleration | Current対PreviousのPost Growth − Previous対PriorのPost Growth | 10% |

各Componentを**同一Project・日・Platform・Window・粒度（TOPICまたはTERM）**のCohort内でMin-Max normalizationします。既知値について `(value − min) / (max − min) × 100`、全既知値が同じなら50。NULLは正規化してもNULLです。Scoreは0〜100、Decimal計算でScoreを小数第2位に丸めます。

```text
Trend Score = Post Growth Score × 0.40
            + Engagement Growth Score × 0.30
            + Engagement Level Score × 0.20
            + Acceleration Score × 0.10
```

**Componentが1つでもNULLならTrend ScoreはNULL。Weightは再配分しません。** 前期間の分母0、Engagement既知値なし等は計算不能です。日付欠測を都合よく埋めません。Trend Full Rebuildは最新PostMetricを使うため、後からSnapshotが追加されると過去trend_dailyも変わり得ます。

## Gap Analysis

Own Post Ratioは期間内の対象Topic一致OWN投稿数 / 同じSNSのOWN全投稿数 × 100。Competitor Post Ratioも競合投稿の同じ基準です。Trendは選択期間内の最新7日Snapshotで、最新ScoreがNULLなら過去の既知Scoreへ戻しません。

```text
Gap Score = Trend Score × (1 − Own Post Ratio / 100)
```

市場Trendが高く、自社の扱う比率が低いTopicほど未対応の機会が大きいという指標です。売上や成功確率を保証しません。TrendまたはOwn RatioがNULLならGapも分類もNULL。Own Ratio=100%ならGap=0を有効な値として保持します。

| Version 1 threshold | Classification | 読み方 |
| --- | --- | --- |
| Trend ≥ 50 / Own < 50 | Opportunity | 市場が伸び、自社の扱いが少ない |
| Trend ≥ 50 / Own ≥ 50 | Balanced | 市場の勢いと自社の扱いが両方高い |
| Trend < 50 / Own ≥ 50 | High Coverage | 自社の扱いが市場の勢いに対して多い |
| Trend < 50 / Own < 50 | Low Priority | 市場の勢いと自社の扱いが両方低い |

Canonical Demoは表12行、座標既知11点（X Circle6 / Instagram Diamond5）。座標不明1行は表に残します。Opportunity Zone、分類の色、SNS別の形で読み分けます。刷新後も11点を表示します。

計算元：[Trend calculation](../../backend/app/services/trend_calculation.py)、[Trend Service](../../backend/app/services/trend_service.py)、[Gap Service](../../backend/app/services/gap_analysis_service.py)。完全な契約は[技術資料](../technical_reference.md)へ。
