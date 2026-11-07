"""Development tab lists only real pipeline adapters (a PROJE_KAYNAK= line), not helper scripts like kum.sh."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sunucu  # noqa: E402


class GelistirmeProjeleri(unittest.TestCase):
    def test_yalniz_uyarlayicilar(self):
        with tempfile.TemporaryDirectory() as kok:
            d = os.path.join(kok, "sistem", "gelistirme"); os.makedirs(d)
            open(os.path.join(d, "turnusol.sh"), "w").write('# x\nPROJE_KAYNAK="$HOME/t"\n')
            open(os.path.join(d, "kum.sh"), "w").write('# sandbox helper\nkum() { :; }\n')
            open(os.path.join(d, "notlar.md"), "w").write('PROJE_KAYNAK=x\n')
            open(os.path.join(d, "Kotu Ad.sh"), "w").write('PROJE_KAYNAK=x\n')
            eski = sunucu.BEYIN
            try:
                sunucu.BEYIN = kok
                self.assertEqual(sunucu.gelistirme_projeleri(), ["turnusol"])
            finally:
                sunucu.BEYIN = eski


if __name__ == "__main__":
    unittest.main()
