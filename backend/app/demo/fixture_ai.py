"""CLI-only fake; production adapters and prompts remain unchanged."""
from app.schemas.insights import AIInsightContent

class DemoClient:
    available = True
    def __init__(self): self.calls = 0
    def generate(self, summary, evidence):
        self.calls += 1
        reach = summary["own_kpi"]["reach"]
        ref = "KPI_REACH"
        trend = evidence["trends"][0]["id"] if evidence["trends"] else ref
        gap = evidence["opportunities"][0]["id"] if evidence["opportunities"] else ref
        return AIInsightContent(summary=f"Demo Fixture：架空CSVの保存済み参考レポート。実OpenAI生成ではありません。Reach {reach['value']}。",
            market_trend="市場の上昇・下降を7日Rollingの根拠で確認する架空例です。",
            own_analysis="媒体別の測定基準を分け、Followersを合算せずに確認してください。",
            improvement_points=["投稿Coverageの低い機会Topicを小規模に検証します。"],
            post_ideas=["上昇Topicの短い検証投稿を作り、同じ期間で結果を比べます。"],
            cautions=["Phase14固定Fixture。実OpenAI API呼出なし。成果保証なし。"],
            references=dict(market_trend=[trend],own_analysis=[ref],improvement_points=[[gap]],post_ideas=[[trend]])), "demo-fixture"
