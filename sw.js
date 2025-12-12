self.addEventListener('push', function(event) {
  const data = event.data ? event.data.json() : { title: "默认标题", body: "没有消息内容" };
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/icon.png'
    })
  );
});
