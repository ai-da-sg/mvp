// 探测后台 HTTPS 反代是否可达
// 自签证书需要放开校验，这里只用于连通性检查
(async () => {
  let s = "FAIL";
  try {
    const r = await fetch("https://127.0.0.1:18444/login", {
      signal: AbortSignal.timeout(6000),
    });
    s = r.status;
  } catch (e) {
    s = (e.cause && e.cause.code) || "FAIL";
  }
  console.log("后台 https://127.0.0.1:18444 → " + s);
})();
