"""Kilit beklerken yazılan 'basliyor' kaydının meşgul sayılması: python3 -m unittest test_ajan_mesgul"""
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import ortak


class AjanMesgulTesti(unittest.TestCase):
    def setUp(self):
        self.gecici = tempfile.TemporaryDirectory()
        yama = mock.patch.object(ortak, "DURUM_DIZINI", self.gecici.name)
        yama.start()
        self.addCleanup(yama.stop)
        self.addCleanup(self.gecici.cleanup)

    def test_basliyor_yasayan_pid_60sn_mesgul(self):
        ortak.durum_yaz("a", {"durum": "basliyor", "pid": os.getpid(), "baslangic_ts": time.time() - 60})
        self.assertTrue(ortak.ajan_mesgul("a"))

    def test_basliyor_olu_pid_60sn_bosta(self):
        p = subprocess.Popen(["true"])
        p.wait()
        ortak.durum_yaz("a", {"durum": "basliyor", "pid": p.pid, "baslangic_ts": time.time() - 60})
        self.assertFalse(ortak.ajan_mesgul("a"))

    def test_basliyor_pid_yok_5sn_mesgul(self):
        ortak.durum_yaz("a", {"durum": "basliyor", "pid": None, "baslangic_ts": time.time() - 5})
        self.assertTrue(ortak.ajan_mesgul("a"))


if __name__ == "__main__":
    unittest.main()
