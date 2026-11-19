"""V1.1 #7 çalışan workflow koşusunu iptal: ofis yalnız /proc ile doğrulanan kosucu sürecine SIGUSR1 yollar;
kosucu claude alt sürecini kapatır, iptal sonucunu yazar, yedek zincirine ya da limit kuyruğuna geçmez.
Gerçek süreçler (python3 -c), model/ağ yok.  python3 -m unittest test_akis_iptal"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import akis_motor
import akis_ofis
import kosucu
import ortak
from test_claude_hesaplar import HesapOrtami

REF = "ak-0123456789ab"


class AjanDurdurTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.d, True)
        for y in (mock.patch.object(ortak, "DURUM_DIZINI", self.d), mock.patch.object(ortak, "KOSU_DIZINI", self.d)):
            y.start()
            self.addCleanup(y.stop)
        self.ortam = akis_ofis.OfisOrtami(mock.Mock())
        os.makedirs(akis_motor.sonuc_dizini())
        self.isaretci = os.path.join(self.d, "sinyal.txt")
        # sahte kosucu: adı kosucu.py, son argümanı arg dosyası; SIGUSR1 gelince dosyaya yazar
        self.betik = os.path.join(self.d, "kosucu.py")
        with open(self.betik, "w") as f:
            f.write("import signal, sys, time\n"
                    f"signal.signal(signal.SIGUSR1, lambda *a: (open({self.isaretci!r}, 'w').write('ok'), sys.exit(0)))\n"
                    "print('hazir', flush=True)\ntime.sleep(30)\n")

    def baslat(self, argv):
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        if "kosucu.py" in argv[1]:
            p.stdout.readline()
        else:
            time.sleep(0.2)
        return p

    def isaret_yaz(self, pid, kosu_id="k1", ref=REF):
        with open(os.path.join(akis_motor.sonuc_dizini(), f"{REF}.basladi.json"), "w") as f:
            json.dump({"ref": ref, "kosu_id": kosu_id, "pid": pid}, f)

    def test_dogrulanan_kosucuya_sinyal(self):
        p = self.baslat([sys.executable, self.betik, os.path.join(self.d, "k1.arg.json")])
        self.isaret_yaz(p.pid)
        self.assertEqual(self.ortam.ajan_durdur(REF), (True, None))
        p.wait(5)
        with open(self.isaretci) as f:
            self.assertEqual(f.read(), "ok")

    def test_baska_surece_sinyal_yok(self):
        for argv, kosu_id in (([sys.executable, "-c", "import time; time.sleep(30)"], "k1"),        # kosucu değil
                              ([sys.executable, self.betik, os.path.join(self.d, "k2.arg.json")], "k1")):  # başka koşu
            p = self.baslat(argv)
            self.isaret_yaz(p.pid, kosu_id)
            durdu, neden = self.ortam.ajan_durdur(REF)
            self.assertFalse(durdu, neden)
            self.assertIsNone(p.poll())
        self.assertFalse(os.path.exists(self.isaretci))

    def test_isaret_yok_ya_da_bozuk(self):
        self.assertFalse(self.ortam.ajan_durdur(REF)[0])
        for pid, ref in ((1, REF), ("12", REF), (os.getpid(), "ak-ffffffffffff")):
            self.isaret_yaz(pid, ref=ref)
            self.assertFalse(self.ortam.ajan_durdur(REF)[0])
        self.assertFalse(self.ortam.ajan_durdur("../x")[0])


class KosucuIptalTest(HesapOrtami):
    def setUp(self):
        super().setUp()
        eski = signal.getsignal(signal.SIGUSR1)
        self.addCleanup(signal.signal, signal.SIGUSR1, eski)
        self.addCleanup(kosucu._IPTAL.update, istendi=False, yukselt=False)

    def test_sinyal_claude_surecini_kapatir_yedege_gecmez(self):
        cocuklar = []
        gercek = subprocess.Popen

        def uzun_surec(komut, **kw):
            kw.pop("env", None)
            p = gercek([sys.executable, "-c", "import time\nprint('{}', flush=True)\ntime.sleep(60)"], **kw)
            cocuklar.append(p)
            return p
        ajan = {"id": "a", "ad": "A", "oda": "o", "model": "sonnet", "cwd": self.d}
        arg = os.path.join(self.d, "arg.json")
        with open(arg, "w") as f:
            json.dump({"ajan": "a", "kosu_id": "k1", "prompt": "görev", "akis_ref": REF}, f)
        zamanlayici = threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGUSR1))
        with mock.patch.object(kosucu.ortak, "ajanlari_yukle", return_value=({"varsayilan_yasak_araclar": []}, {"a": ajan})), \
                mock.patch.object(kosucu, "api_anahtari", return_value=(None, None)), \
                mock.patch.object(kosucu.subprocess, "Popen", side_effect=uzun_surec), \
                mock.patch.object(kosucu, "yedek_kos") as yedek, \
                mock.patch.object(kosucu, "limit_bekleyen_yaz") as limit:
            zamanlayici.start()
            t0 = time.time()
            kosucu.kos(arg)
        self.assertLess(time.time() - t0, 20)
        self.assertEqual(self.bitis["hata"], kosucu.IPTAL_HATASI)
        self.assertEqual(len(cocuklar), 1)                 # ikinci hesap/yedek denenmedi
        self.assertIsNotNone(cocuklar[0].poll())           # claude süreci yetim kalmadı
        yedek.assert_not_called()
        limit.assert_not_called()

    def test_workflow_disi_kosuda_isleyici_yok(self):
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
        ajan = {"id": "a", "ad": "A", "oda": "o", "model": "sonnet", "cwd": self.d}
        arg = os.path.join(self.d, "arg.json")
        with open(arg, "w") as f:
            json.dump({"ajan": "a", "kosu_id": "k1", "prompt": "görev"}, f)
        import test_claude_api_yedek as tay
        with mock.patch.object(kosucu.ortak, "ajanlari_yukle", return_value=({"varsayilan_yasak_araclar": []}, {"a": ajan})), \
                mock.patch.object(kosucu, "api_anahtari", return_value=(None, None)), \
                mock.patch.object(kosucu.subprocess, "Popen", side_effect=[tay.basarili_surec()]):
            kosucu.kos(arg)
        self.assertEqual(signal.getsignal(signal.SIGUSR1), signal.SIG_IGN)


class MotorIptalNotuTest(unittest.TestCase):
    def test_not_sinyal_sonucunu_soyler(self):
        from test_akis_motor import MotorTabani

        class T(MotorTabani):
            def runTest(self_):
                from test_akis_birim import taban_tanim
                t = self_.tanim(taban_tanim())
                k = self_.m.baslat(t["id"], {"konu": "x"})["run_id"]
                self_.m.tur()
                self_.ortam.durdur_sonucu = (True, None)
                d = self_.m.iptal(k)
                self_.assertEqual(self_.ortam.durdurulan, [self_.son_ref()])
                self_.assertTrue(any("durdurma sinyali gönderildi" in n for n in d["notlar"]), d["notlar"])
        r = unittest.TestResult()
        T().run(r)
        self.assertTrue(r.wasSuccessful(), r.failures + r.errors)


if __name__ == "__main__":
    unittest.main()
