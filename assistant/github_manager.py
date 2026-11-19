"""Безопасный клиент GitHub API для Димасика."""
import keyring
import requests

API = "https://api.github.com"
SERVICE = "Dimasik-GitHub"
TIMEOUT = 20


class GitHubError(RuntimeError):
    pass


class GitHubManager:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    @property
    def connected(self):
        return bool(keyring.get_password(SERVICE, "token"))

    def connect(self, token):
        token = str(token).strip()
        if not token:
            raise GitHubError("Вставь GitHub Personal Access Token.")
        old = self.session.headers.get("Authorization")
        self.session.headers["Authorization"] = "Bearer " + token
        try:
            response = self.session.get(API + "/user", timeout=TIMEOUT)
            response.raise_for_status()
            user = response.json()
            keyring.set_password(SERVICE, "token", token)
            return user
        except Exception:
            if old:
                self.session.headers["Authorization"] = old
            else:
                self.session.headers.pop("Authorization", None)
            raise GitHubError("Не удалось подключить GitHub. Проверь токен и его разрешения.")

    def disconnect(self):
        keyring.delete_password(SERVICE, "token")
        self.session.headers.pop("Authorization", None)

    def _auth(self):
        token = keyring.get_password(SERVICE, "token")
        if not token:
            raise GitHubError("Сначала подключи GitHub в разделе интеграций.")
        self.session.headers["Authorization"] = "Bearer " + token

    def _request(self, method, path, **kwargs):
        self._auth()
        response = self.session.request(method, API + path, timeout=TIMEOUT, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.reason)
            except ValueError:
                detail = response.reason
            raise GitHubError("GitHub API: " + str(detail))
        return response.json() if response.content else {}

    def list_repositories(self):
        return self._request("GET", "/user/repos", params={
            "sort": "updated", "per_page": 100, "affiliation": "owner,collaborator"
        })

    def get_file(self, owner, repo, path, branch=""):
        params = {"ref": branch} if branch else {}
        item = self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)
        if item.get("type") != "file":
            raise GitHubError("Указанный путь не является файлом.")
        import base64
        return base64.b64decode(item["content"]).decode("utf-8"), item["sha"]

    def create_branch(self, owner, repo, branch, base=""):
        if not branch or branch in ("main", "master"):
            raise GitHubError("Укажи отдельное имя ветки, не main/master.")
        source = base or self._request("GET", f"/repos/{owner}/{repo}").get("default_branch", "main")
        ref = self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{source}")
        return self._request("POST", f"/repos/{owner}/{repo}/git/refs", json={
            "ref": "refs/heads/" + branch, "sha": ref["object"]["sha"]
        })

    def write_file(self, owner, repo, path, content, message, branch, sha=None):
        if not branch or branch in ("main", "master"):
            raise GitHubError("Изменения разрешено отправлять только в отдельную ветку.")
        payload = {"message": message, "content": __import__("base64").b64encode(
            content.encode("utf-8")).decode("ascii"), "branch": branch}
        if sha:
            payload["sha"] = sha
        return self._request("PUT", f"/repos/{owner}/{repo}/contents/{path}", json=payload)

    def create_pull_request(self, owner, repo, title, body, branch, base=""):
        if not branch or branch in ("main", "master"):
            raise GitHubError("Pull Request должен идти из отдельной ветки.")
        default = base or self._request("GET", f"/repos/{owner}/{repo}").get("default_branch", "main")
        return self._request("POST", f"/repos/{owner}/{repo}/pulls", json={
            "title": title, "body": body, "head": branch, "base": default
        })
