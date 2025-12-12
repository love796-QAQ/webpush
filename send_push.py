from pywebpush import webpush
import json
from urllib.parse import urlparse


# Step 1: 粘贴 subscription 对象（从浏览器控制台复制）
subscription_info = {
    "endpoint": "https://web.push.apple.com/QIfgamL7FS8br6fcYkwvdsHKgRfTU3BtMf7TP29u5E8Izt9SITS2_U1nh77vxNOJ42RN0Msoo2H0chCNYJ61_S2DbENDqiwfbTn0lanQlO1WmHMFr7J4mjZLbv8aivKJxjOzgWMvkOJtki0zLUnOc-LV4-gSoeQK39y74cuREFU",
  "keys": {
    "p256dh": "BBve75J0dJ4je_IhCeLSrJRg-gJh8-CV1HiHP9D3WhHyxK2MA7jo-khwv4IJgVH4mbrQUtiT4LqpTCdAdq6T4jo",
    "auth": "KVY7s0aoDXJ9s7zCzURyJQ"
    }
}

# Step 2: 填入你生成的 VAPID 私钥
vapid_private_key = "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgxKqipyw9KxiYwvvcPnzVFxTH8ZmejJNue60qDdTWNaKhRANCAASujVTyjP7egf/Cn/UQ+dwNGspHrUJP6+dGRD6FrvVaMQK6P1114E1WsSa0JtJJc7bpIQb0+f/I7f+44MPO6RvY"
vapid_public_key = "你的公钥"

# 提取 audience
parsed = urlparse(subscription_info["endpoint"])
audience = f"{parsed.scheme}://{parsed.netloc}"

vapid_claims = {
    "sub": "mailto:you@example.com",
    "aud": audience  # ✅ 关键修复
}

# Step 3: 构建要推送的内容
payload = json.dumps({
    "title": "🎉 来自后台的通知",
    "body": "网页关闭后也能收到的推送！"
})

# Step 4: 发起推送
webpush(
    subscription_info=subscription_info,
    data=payload,
    vapid_private_key=vapid_private_key,
    vapid_claims=vapid_claims
)

print("推送完成 ✅")
