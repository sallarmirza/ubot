class NormalizeLeadingSlashesMiddleware:
	def __init__(self, app):
		self.app = app

	async def __call__(self, scope, receive, send):
		if scope["type"] == "http" and scope["path"].startswith("//"):
			path = "/" + scope["path"].lstrip("/")
			raw_path = scope.get("raw_path")
			scope = {**scope, "path": path}
			if raw_path is not None:
				scope["raw_path"] = b"/" + raw_path.lstrip(b"/")

		await self.app(scope, receive, send)
