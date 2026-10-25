#!/usr/bin/env python3
"""
Unit and integration tests for ResolveSync.
Tests DRP XML parsing, path mapping across OS boundaries, and edge case handling.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

from resolvesync import (
    DRPParser,
    MediaItem,
    PathMapper,
    PathMappingRule,
    ResolveSyncApp,
    launch_davinci_resolve,
)


class TestDRPParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_mock_drp(self, xml_dict: dict) -> str:
        """Helper to create a zip file with .drp extension containing the given XML files."""
        drp_path = os.path.join(self.temp_dir, "test_project.drp")
        with zipfile.ZipFile(drp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, content in xml_dict.items():
                zf.writestr(name, content)
        return drp_path

    def test_extract_media_paths_standard(self):
        project_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Project>
            <MediaPool>
                <Folder name="Footage">
                    <Clip>
                        <FilePath>D:\\Projects\\Video1\\A001_C001.mov</FilePath>
                    </Clip>
                    <Clip>
                        <FilePath>D:/Projects/Video1/B-Roll/A002_C002.mp4</FilePath>
                    </Clip>
                    <Clip>
                        <AudioFilePath>E:\\AudioLibrary\\SoundEffects\\whoosh.wav</AudioFilePath>
                    </Clip>
                </Folder>
            </MediaPool>
        </Project>
        """
        drp_path = self.create_mock_drp({"project.xml": project_xml})
        parser = DRPParser()
        paths = parser.extract_media_paths(drp_path)

        self.assertEqual(len(paths), 3)
        self.assertIn("D:\\Projects\\Video1\\A001_C001.mov", paths)
        self.assertIn("D:/Projects/Video1/B-Roll/A002_C002.mp4", paths)
        self.assertIn("E:\\AudioLibrary\\SoundEffects\\whoosh.wav", paths)

    def test_url_encoding_and_file_uris(self):
        project_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <SM_MediaPool>
            <Item>
                <FilePath>file://localhost/Volumes/Production%20Drive/Footage%202024/Clip%2001.mov</FilePath>
            </Item>
            <Item>
                <FilePath>file:///D:/Footage%20Folder/Take%2001.braw</FilePath>
            </Item>
        </SM_MediaPool>
        """
        drp_path = self.create_mock_drp({"project.xml": project_xml})
        parser = DRPParser()
        paths = parser.extract_media_paths(drp_path)

        self.assertEqual(len(paths), 2)
        self.assertIn("/Volumes/Production Drive/Footage 2024/Clip 01.mov", paths)
        self.assertIn("D:/Footage Folder/Take 01.braw", paths)

    def test_skip_cache_and_internal_files(self):
        project_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Project>
            <Clip>
                <FilePath>D:\\Cache\\Clip01.dvcc</FilePath>
            </Clip>
            <Clip>
                <FilePath>D:\\Projects\\Still.gallery</FilePath>
            </Clip>
            <Clip>
                <FilePath>D:\\Projects\\Grade.drx</FilePath>
            </Clip>
            <Clip>
                <FilePath>D:\\Projects\\RealFootage.mxf</FilePath>
            </Clip>
        </Project>
        """
        drp_path = self.create_mock_drp({"project.xml": project_xml})
        parser = DRPParser()
        paths = parser.extract_media_paths(drp_path)

        # Only the .mxf file should be extracted; cache files skipped
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], "D:\\Projects\\RealFootage.mxf")

    def test_nested_xml_files_in_subfolders(self):
        drp_path = self.create_mock_drp({
            "project.xml": "<Project><MediaPoolItem filePath='D:\\Footage\\Clip1.mov'/></Project>",
            "MediaPool/Bin1.xml": "<Bin><Clip><FilePath>D:\\Footage\\Clip2.mov</FilePath></Clip></Bin>",
        })
        parser = DRPParser()
        paths = parser.extract_media_paths(drp_path)
        self.assertEqual(len(paths), 2)
        self.assertIn("D:\\Footage\\Clip1.mov", paths)
        self.assertIn("D:\\Footage\\Clip2.mov", paths)


class TestPathMapper(unittest.TestCase):
    def test_windows_to_posix_translation(self):
        rule = PathMappingRule(
            name="Windows to Mac and Remote Linux",
            drp_prefix="D:\\Projects\\Video1",
            local_prefix="/Users/Me/Projects/Video1",
            remote_prefix="/srv/media/projects/Video1",
        )
        mapper = PathMapper([rule])

        drp_path = "D:\\Projects\\Video1\\B-Roll\\Subfolder\\clip01.mp4"
        local_p, remote_p, matched_rule = mapper.map_path(drp_path)

        self.assertIsNotNone(matched_rule)
        # Remote SFTP path should always be POSIX with forward slashes
        self.assertEqual(remote_p, "/srv/media/projects/Video1/B-Roll/Subfolder/clip01.mp4")
        # Local path should contain the correct path parts
        self.assertTrue(local_p.endswith(os.path.join("Subfolder", "clip01.mp4")))

    def test_mac_to_windows_translation(self):
        rule = PathMappingRule(
            name="Mac to Windows Local",
            drp_prefix="/Volumes/FastSSD/Footage",
            local_prefix="E:\\Footage",
            remote_prefix="/mnt/storage/Footage",
        )
        mapper = PathMapper([rule])

        drp_path = "/Volumes/FastSSD/Footage/Day1/Interview/camA.mov"
        local_p, remote_p, matched_rule = mapper.map_path(drp_path)

        self.assertIsNotNone(matched_rule)
        self.assertEqual(remote_p, "/mnt/storage/Footage/Day1/Interview/camA.mov")
        self.assertTrue(local_p.endswith(os.path.join("Interview", "camA.mov")))

    def test_case_insensitive_drive_letter_matching(self):
        rule = PathMappingRule(
            name="Lower Drive Letter",
            drp_prefix="d:\\projects",
            local_prefix="C:\\Projects",
            remote_prefix="/srv/projects",
        )
        mapper = PathMapper([rule])

        drp_path = "D:\\PROJECTS\\Scene1\\Take1.mp4"
        local_p, remote_p, matched_rule = mapper.map_path(drp_path)
        self.assertIsNotNone(matched_rule)
        self.assertEqual(remote_p, "/srv/projects/Scene1/Take1.mp4")

    def test_no_matching_rule(self):
        rule = PathMappingRule(
            name="Specific Folder",
            drp_prefix="D:\\Projects",
            local_prefix="C:\\Projects",
            remote_prefix="/srv/projects",
        )
        mapper = PathMapper([rule])

        drp_path = "Z:\\Unrelated\\Clip.mov"
        local_p, remote_p, matched_rule = mapper.map_path(drp_path)
        self.assertIsNone(matched_rule)
        self.assertIsNone(local_p)
        self.assertIsNone(remote_p)

    def test_auto_mapping_windows_drive(self):
        mapper = PathMapper(auto_fallback=True)
        drp_path = "D:\\Users\\zigav\\Videos\\jp.mp4"
        local_p, remote_p, matched_rule = mapper.map_path(drp_path)
        self.assertIsNotNone(matched_rule)
        self.assertEqual(remote_p, "/media/D/Users/zigav/Videos/jp.mp4")

    def test_auto_mapping_mac_destination(self):
        mac_sync_root = "/Volumes/Samsung_T7/ProjectMedia"
        mapper = PathMapper(auto_fallback=True, sync_root=mac_sync_root)
        drp_path = "D:\\Users\\zigav\\Videos\\take1.mov"
        local_p, remote_p, matched_rule = mapper.map_path(drp_path, sync_root=mac_sync_root)
        self.assertIsNotNone(matched_rule)
        self.assertEqual(remote_p, "/media/D/Users/zigav/Videos/take1.mov")
        # Verify it maps under the chosen sync destination preserving drive and path
        self.assertTrue("Samsung_T7" in local_p)
        self.assertTrue("take1.mov" in local_p)

    def test_auto_mapping_unc_share(self):
        mapper = PathMapper(auto_fallback=True)
        drp_path = "\\\\nas01\\footage\\day1\\take02.braw"
        local_p, remote_p, matched_rule = mapper.map_path(drp_path)
        self.assertIsNotNone(matched_rule)
        self.assertEqual(remote_p, "/media/SMB/nas01/footage/day1/take02.braw")

    def test_davinci_project_discoverer(self):
        from resolvesync import DaVinciProjectDiscoverer
        recent = DaVinciProjectDiscoverer.get_recent_projects()
        self.assertIsInstance(recent, list)
        live = DaVinciProjectDiscoverer.get_live_project()
        self.assertIn("status", live)

    def test_analyze_inventory_with_file_paths(self):
        from resolvesync import ResolveSyncApp
        cfg_cand = os.path.join(os.path.dirname(__file__), "config.example.json")
        if not os.path.exists(cfg_cand):
            cfg_cand = "config.example.json"
        app = ResolveSyncApp(config_path=cfg_cand)
        custom_paths = [
            "D:\\Users\\zigav\\Videos\\take1.mov",
            "D:\\Users\\zigav\\Videos\\take2.braw",
        ]
        items = app.analyze_inventory(file_paths=custom_paths, check_remote=False)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].remote_path, "/media/D/Users/zigav/Videos/take1.mov")
        self.assertEqual(items[1].remote_path, "/media/D/Users/zigav/Videos/take2.braw")


class TestWebServer(unittest.TestCase):
    def setUp(self):
        try:
            from web_server import app
            app.config['TESTING'] = True
            self.client = app.test_client()
        except ImportError:
            self.skipTest("web_server module not installed on client workstation")

    def test_homepage_render(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ResolveSync", response.data)
        self.assertIn(b"TrueNAS Server Status", response.data)

    def test_api_config(self):
        response = self.client.get('/api/config')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("server", data)
        self.assertIn("path_mappings", data)

    def test_api_test_mapping(self):
        response = self.client.post('/api/test-mapping', json={"drp_path": "D:\\Footage\\ProjectAlpha\\clip.mov"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("matched"))
        self.assertIn("clip.mov", data.get("remote_path"))


class TestDaVinciPostgresReader(unittest.TestCase):
    def test_parse_resolvedbkey_xml_string(self):
        from resolvesync import DaVinciPostgresReader
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <DBAccessKey>
          <hostIPAddress>thekingziga.com</hostIPAddress>
          <dbName>main</dbName>
          <dbUsername>main</dbUsername>
          <dbPassword>12345</dbPassword>
        </DBAccessKey>
        """
        parsed = DaVinciPostgresReader.parse_resolvedbkey(sample_xml)
        self.assertEqual(parsed["host"], "thekingziga.com")
        self.assertEqual(parsed["port"], 5432)
        self.assertEqual(parsed["dbname"], "main")
        self.assertEqual(parsed["user"], "main")
        self.assertEqual(parsed["password"], "12345")

    def test_parse_resolvedbkey_with_port(self):
        from resolvesync import DaVinciPostgresReader
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <DBAccessKey>
          <hostIPAddress>192.168.1.50:5433</hostIPAddress>
          <dbName>studio_db</dbName>
          <dbUsername>resolve_user</dbUsername>
          <dbPassword>secret</dbPassword>
        </DBAccessKey>
        """
        parsed = DaVinciPostgresReader.parse_resolvedbkey(sample_xml)
        self.assertEqual(parsed["host"], "192.168.1.50")
        self.assertEqual(parsed["port"], 5433)
        self.assertEqual(parsed["dbname"], "studio_db")

    def test_from_config(self):
        from resolvesync import DaVinciPostgresReader
        cfg = {
            "postgres": {
                "enabled": True,
                "host": "192.168.69.29",
                "port": 5432,
                "user": "main",
                "password": "12345",
                "dbname": "main",
            }
        }
        reader = DaVinciPostgresReader.from_config(cfg)
        self.assertIsNotNone(reader)
        self.assertEqual(reader.host, "192.168.69.29")
        self.assertEqual(reader.dbname, "main")

    def test_clip_path_regex_extraction(self):
        import re
        clip_bytes = b'\x00\x00\x00\x02\x00\x00\x00\x96\x81(\xb5/\xfd \x96e\x04\x00D\x08\n\x12/Users/ziga/Movies\x12\x11\xc5\xbdiga_loop_#1.mov\x1a\x18Fri Oct  2 09:18:03 2026*\x04avc1'
        m = re.search(rb'\n[\x01-\x7f]([a-zA-Z]:[^\x00-\x1f\x7f]+|\/[^\x00-\x1f\x7f]+)\x12[\x01-\x7f]([^\x00-\x1f\x7f]+?\.[a-zA-Z0-9]{2,5})', clip_bytes)
        self.assertIsNotNone(m)
        d = m.group(1).decode("utf-8", errors="ignore").strip()
        f = m.group(2).decode("utf-8", errors="ignore").strip()
        self.assertEqual(d, "/Users/ziga/Movies")
        self.assertEqual(f, "Žiga_loop_#1.mov")


    def test_calculate_mapped_mounts(self):
        from desktop_app import calculate_mapped_mounts
        paths = [
            r"\Users\ziga\Pictures\lidl.png",
            "/Users/ziga/Movies/zigabeepeffect.mp4",
            r"D:\Users\zigav\Videos\take1.mp4",
        ]
        # Test Windows workstation mapping Mac paths
        win_recs = calculate_mapped_mounts(paths, r"D:\DAVINCI", is_win=True)
        self.assertTrue(any(r["remote"] == "/Users/ziga/" for r in win_recs))
        self.assertTrue(any("Users" in r["local"] and "ziga" in r["local"] for r in win_recs))

        # Test Mac workstation mapping Windows paths
        mac_recs = calculate_mapped_mounts(paths, "/Volumes/SSD/Media", is_win=False)
        self.assertTrue(any(r["remote"] == "D:\\" for r in mac_recs))
        self.assertTrue(any("D" in r["local"] for r in mac_recs))

    def test_davinci_pref_manager(self):
        from resolvesync import DaVinciPreferencesManager
        import tempfile, shutil

        tmpdir = tempfile.mkdtemp()
        try:
            cfg_data = os.path.join(tmpdir, ".config.data")
            cfg_dat = os.path.join(tmpdir, "config.dat")

            # Setup initial mock files with the exact user slash mismatch
            with open(cfg_data, "w", encoding="utf-8") as f:
                f.write(
                    "IoFsNum = 2\n"
                    "IoFsMount_1 = D:\\Users\\zigav\\Videos\n"
                    "IoFsMappedMount_1 = \n"
                    "IoFsDirectIO_1 = 1\n"
                    "IoFsMount_2 = D:\\DAVINCI\\Root\\Users\\ziga\n"
                    "IoFsMappedMount_2 = /Users/ziga/\n"
                    "IoFsDirectIO_2 = 1\n"
                    "ShowAllMountedVolumes = 1\n"
                )

            with open(cfg_dat, "w", encoding="utf-8") as f:
                f.write(
                    "Site.Count = 1\n"
                    "Site.1.LocalEnabled = 1\n"
                    "Site.1.FS.Count = 3\n\n"
                    "Site.1.FS.1.Type = IOFileSys\n"
                    "Site.1.FS.1.Root = D:\\Users\\zigav\\Videos\n"
                    "Site.1.FS.1.MappedRoot = \n"
                    "Site.1.FS.1.DIO = 1\n"
                    "Site.1.FS.1.BrightClip = 0\n\n"
                    "Site.1.FS.2.Type = IOFileSys\n"
                    "Site.1.FS.2.Root = D:\\DAVINCI\\Root\\Users\\ziga\n"
                    "Site.1.FS.2.MappedRoot = /Users/ziga/\n"
                    "Site.1.FS.2.DIO = 1\n"
                    "Site.1.FS.2.BrightClip = 0\n\n"
                    "Site.1.FS.3.Type = IOFileSys\n"
                    "Site.1.FS.3.Root = ResolveVirtual\n"
                    "Site.1.FS.3.MappedRoot = \n"
                    "Site.1.FS.3.DIO = 1\n"
                    "Site.1.FS.3.BrightClip = 0\n\n"
                    "Site.1.CmdRT.Count = 1\n"
                )

            mgr = DaVinciPreferencesManager(tmpdir)
            self.assertTrue(mgr.exists())

            # 1. Test reading mounts
            mounts = mgr.read_mounts()
            self.assertEqual(len(mounts), 2)
            self.assertEqual(mounts[1]["mapped"], "/Users/ziga/")

            # 2. Test slash mismatch detection (Root missing trailing slash)
            status = mgr.check_mount_status("/Users/ziga/", r"D:\DAVINCI\Root\Users\ziga\\")
            self.assertEqual(status["status"], "slash_mismatch")
            self.assertTrue(status["needs_fix"])

            # 3. Test missing mount detection
            status_missing = mgr.check_mount_status("/Volumes/SSD/", r"D:\DAVINCI\Volumes\SSD\\")
            self.assertEqual(status_missing["status"], "missing")
            self.assertTrue(status_missing["needs_fix"])

            # 4. Test auto-fixing / updating mount
            ok, msg = mgr.add_or_update_mount("/Users/ziga/", r"D:\DAVINCI\Root\Users\ziga")
            self.assertTrue(ok)

            # 5. Verify status is now 'active'
            status_fixed = mgr.check_mount_status("/Users/ziga/", r"D:\DAVINCI\Root\Users\ziga\\")
            self.assertEqual(status_fixed["status"], "active")
            self.assertFalse(status_fixed["needs_fix"])

            # 6. Verify backup files exist
            self.assertTrue(os.path.exists(cfg_data + ".resolvesync.bak"))
            self.assertTrue(os.path.exists(cfg_dat + ".resolvesync.bak"))

            # 7. Verify config.dat still contains ResolveVirtual at the end
            with open(cfg_dat, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("ResolveVirtual", content)
            self.assertIn("Site.1.CmdRT.Count = 1", content)
            self.assertIn("D:\\DAVINCI\\Root\\Users\\ziga\\", content)

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestProxyAndLauncher(unittest.TestCase):
    """Tests for selective proxy filtering and DaVinci Resolve process launcher."""

    def test_proxy_file_detection(self):
        # Recognized proxy conventions
        self.assertTrue(MediaItem.is_proxy_file(r"D:\Footage\Proxy\A001_C001.mov"))
        self.assertTrue(MediaItem.is_proxy_file(r"/Volumes/SSD/Footage/Proxies/take1.mp4"))
        self.assertTrue(MediaItem.is_proxy_file(r"D:\Footage\A001_C001_Proxy.mov"))
        self.assertTrue(MediaItem.is_proxy_file(r"D:\Footage\interview-proxy.mp4"))
        self.assertTrue(MediaItem.is_proxy_file(r"D:\Footage\ProxyMedia\clip.braw"))
        self.assertTrue(MediaItem.is_proxy_file(r"D:\Footage\LowRes\broll.mov"))

        # Recognized original conventions (not proxies)
        self.assertFalse(MediaItem.is_proxy_file(r"D:\Footage\A001_C001.mov"))
        self.assertFalse(MediaItem.is_proxy_file(r"D:\Footage\Master\take1.mp4"))
        self.assertFalse(MediaItem.is_proxy_file(r"D:\Footage\broll.mov"))

    def test_media_item_proxy_attribute(self):
        item_orig = MediaItem(drp_path=r"D:\Footage\A001_C001.mov")
        self.assertFalse(item_orig.is_proxy)

        item_proxy = MediaItem(drp_path=r"D:\Footage\Proxy\A001_C001.mov")
        self.assertTrue(item_proxy.is_proxy)

    def test_media_filter_selective_sync(self):
        cfg = {
            "server": {},
            "path_mappings": [],
            "sync_options": {"auto_map_unmatched": True}
        }
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            json.dump(cfg, f)
            cfg_path = f.name

        try:
            app = ResolveSyncApp(config_path=cfg_path)
            sample_clips = [
                r"D:\Media\CamA\A001.mov",
                r"D:\Media\CamA\Proxy\A001_Proxy.mov",
                r"D:\Media\CamB\B001.mov",
                r"D:\Media\CamB\Proxy\B001_Proxy.mov",
            ]

            # Filter: All
            all_items = app.analyze_inventory(file_paths=sample_clips, check_remote=False, media_filter="all")
            self.assertEqual(len(all_items), 4)

            # Filter: Proxies Only
            proxy_items = app.analyze_inventory(file_paths=sample_clips, check_remote=False, media_filter="proxies_only")
            self.assertEqual(len(proxy_items), 2)
            self.assertTrue(all(i.is_proxy for i in proxy_items))

            # Filter: Originals Only
            orig_items = app.analyze_inventory(file_paths=sample_clips, check_remote=False, media_filter="originals_only")
            self.assertEqual(len(orig_items), 2)
            self.assertTrue(all(not i.is_proxy for i in orig_items))
        finally:
            if os.path.exists(cfg_path):
                os.remove(cfg_path)

    def test_companion_local_proxy_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_file = os.path.join(tmpdir, "clipA.mp4")
            with open(orig_file, "w") as f:
                f.write("orig")
            
            proxy_dir = os.path.join(tmpdir, "Proxy")
            os.makedirs(proxy_dir)
            proxy_file = os.path.join(proxy_dir, "clipA.mov")
            with open(proxy_file, "w") as f:
                f.write("proxy")
            
            # 1. Direct find_local_proxies call
            found = MediaItem.find_local_proxies(orig_file)
            self.assertEqual(len(found), 1)
            self.assertEqual(os.path.normpath(found[0]), os.path.normpath(proxy_file))

            # 2. Inventory auto-discovery
            cfg = {
                "server": {},
                "path_mappings": [],
                "sync_options": {"auto_map_unmatched": True}
            }
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
                json.dump(cfg, f)
                cfg_path = f.name
            try:
                app = ResolveSyncApp(config_path=cfg_path)
                items = app.analyze_inventory(file_paths=[orig_file], check_remote=False, media_filter="all")
                # Should find both original and discovered proxy
                self.assertEqual(len(items), 2)
                proxy_items = [i for i in items if i.is_proxy]
                self.assertEqual(len(proxy_items), 1)
                self.assertEqual(os.path.normpath(proxy_items[0].local_path), os.path.normpath(proxy_file))
            finally:
                if os.path.exists(cfg_path):
                    os.remove(cfg_path)

    def test_run_selected_items_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = os.path.join(tmpdir, "file1.mp4")
            file2 = os.path.join(tmpdir, "file2.mp4")
            with open(file1, "w") as f: f.write("1")
            with open(file2, "w") as f: f.write("2")

            cfg = {
                "server": {},
                "path_mappings": [],
                "sync_options": {"auto_map_unmatched": True}
            }
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
                json.dump(cfg, f)
                cfg_path = f.name
            try:
                app = ResolveSyncApp(config_path=cfg_path)
                logged_msgs = []
                # Pass only file1 in selected_items
                code = app.run(
                    file_paths=[file1, file2],
                    mode="dry_run",
                    dry_run=True,
                    selected_items=[file1],
                    log_callback=lambda msg: logged_msgs.append(msg)
                )
                self.assertEqual(code, 0)
                # Verify that selective sync message logged
                self.assertTrue(any("Selective Sync: Filtered to 1 selected file(s)" in m for m in logged_msgs))
            finally:
                if os.path.exists(cfg_path):
                    os.remove(cfg_path)

    def test_immediate_cancellation(self):
        from resolvesync import SyncCancelledError, HTTPServerSyncEngine
        engine = HTTPServerSyncEngine("http://127.0.0.1:9999")
        # Test download cancellation
        with self.assertRaises(SyncCancelledError):
            engine.download_file("rem/clip.mp4", "loc/clip.mp4", is_cancelled=lambda: True)

        # Test upload cancellation
        with self.assertRaises(SyncCancelledError):
            engine.upload_file("loc/clip.mp4", "rem/clip.mp4", is_cancelled=lambda: True)

    def test_debug_logging_toggle(self):
        import logging
        from resolvesync import set_debug_logging
        set_debug_logging(True)
        self.assertEqual(logging.getLogger().level, logging.DEBUG)
        set_debug_logging(False)
        self.assertEqual(logging.getLogger().level, logging.INFO)

    def test_launch_davinci_resolve_signature(self):
        from unittest.mock import patch
        with patch("subprocess.Popen") as mock_popen:
            res = launch_davinci_resolve(drp_path=None)
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 2)
            self.assertIsInstance(res[0], bool)
            self.assertIsInstance(res[1], str)


    def test_http_hub_url_normalization(self):
        from resolvesync import HTTPServerSyncEngine
        self.assertEqual(HTTPServerSyncEngine.normalize_url("thekingziga.com:5000"), "http://thekingziga.com:5000")
        self.assertEqual(HTTPServerSyncEngine.normalize_url("http://192.168.1.3:5000/"), "http://192.168.1.3:5000")
        self.assertEqual(HTTPServerSyncEngine.normalize_url("https://hub.example.com"), "https://hub.example.com")
        self.assertEqual(HTTPServerSyncEngine.normalize_url(""), "")

    def test_http_hub_fallback_logic(self):
        from resolvesync import HTTPServerSyncEngine
        engine = HTTPServerSyncEngine("http://192.168.254.254:5000", alt_server_url="http://127.0.0.1:5000")
        cands = engine._get_candidates()
        self.assertIn("http://192.168.254.254:5000", cands)
        self.assertIn("http://127.0.0.1:5000", cands)

    def test_auto_map_drive_letter_structure(self):
        from resolvesync import PathMapper
        mapper = PathMapper(rules=[], auto_fallback=True)
        local_p, remote_p, rule = mapper.map_path("D:\\Footage\\Clip1.mov", sync_root="C:\\DAVINCI")
        self.assertEqual(remote_p, "/media/D/Footage/Clip1.mov")
        self.assertTrue(local_p.endswith("Footage\\Clip1.mov") or local_p.endswith("Footage/Clip1.mov"))


if __name__ == "__main__":
    unittest.main()
