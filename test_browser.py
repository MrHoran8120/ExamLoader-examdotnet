from unittest.mock import patch
import unittest

from examnet import browser


@patch("examnet.browser.sys.platform", "win32")
class FindBrowserWindowsTests(unittest.TestCase):
    def test_prefers_chrome_when_installed(self):
        with patch("examnet.browser._find_windows_browser", side_effect=lambda exe, rel: rf"C:\x\{exe}"):
            self.assertEqual(browser.find_browser(), ("Chrome", r"C:\x\chrome.exe"))

    def test_falls_back_to_edge_without_chrome(self):
        def fake_find(exe_name, relative_path):
            return r"C:\x\msedge.exe" if exe_name == "msedge.exe" else None

        with patch("examnet.browser._find_windows_browser", side_effect=fake_find):
            self.assertEqual(browser.find_browser(), ("Edge", r"C:\x\msedge.exe"))

    def test_raises_clear_error_when_no_browser(self):
        with patch("examnet.browser._find_windows_browser", return_value=None):
            with self.assertRaises(browser.BrowserNotFoundError) as ctx:
                browser.find_browser()
        self.assertIn("Chrome", str(ctx.exception))

    def test_uses_per_user_install_when_registry_has_no_entry(self):
        def fake_isfile(path):
            return path == r"C:\Users\T\AppData\Local\Google\Chrome\Application\chrome.exe"

        env = {"PROGRAMFILES": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\T\AppData\Local"}
        with patch("examnet.browser._registry_app_path", return_value=None), patch.dict(
            "examnet.browser.os.environ", env, clear=True
        ), patch("examnet.browser.os.path.isfile", side_effect=fake_isfile):
            path = browser._find_windows_browser("chrome.exe", r"Google\Chrome\Application\chrome.exe")
        self.assertEqual(path, r"C:\Users\T\AppData\Local\Google\Chrome\Application\chrome.exe")


class LaunchArgsTests(unittest.TestCase):
    def test_launch_args_use_separate_profile_per_browser(self):
        with patch("examnet.browser.browser_profile_dir", side_effect=lambda name: f"/profiles/{name.lower()}"):
            args = browser.browser_launch_args("msedge.exe", "Edge", port=9333, start_url="https://exam.net")
        self.assertEqual(args[0], "msedge.exe")
        self.assertIn("--remote-debugging-port=9333", args)
        self.assertIn("--user-data-dir=/profiles/edge", args)
        self.assertEqual(args[-1], "https://exam.net")


if __name__ == "__main__":
    unittest.main()
