import unittest

from app.core.tools import _is_paywalled_by_signals


class PaywallDetectionTests(unittest.TestCase):
    def test_subscription_chrome_and_comments_are_not_enough(self):
        html = """
        <html>
          <body>
            <!-- paywall label (only for non-subscribers) -->
            <article>
              <p>OpenAI hat noch ein paar mehr Multimillionaere geschaffen.</p>
              <p>Das Unternehmen hat einen Aktienverkauf ueber rund 7 Milliarden Dollar abgeschlossen.</p>
            </article>
            <a href="/subscription">Jetzt abonnieren</a>
            <button>Newsletter abonnieren</button>
          </body>
        </html>
        """.lower()

        self.assertEqual(_is_paywalled_by_signals(html), (False, 0, []))

    def test_jsonld_paywall_remains_strong_signal(self):
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {"isAccessibleForFree": false}
            </script>
          </head>
          <body><article>Nur ein kurzer Auszug.</article></body>
        </html>
        """.lower()

        is_paywalled, score, reasons = _is_paywalled_by_signals(html)

        self.assertTrue(is_paywalled)
        self.assertGreaterEqual(score, 90)
        self.assertIn("jsonld:isaccessibleforfree=false", reasons)

    def test_access_specific_subscribe_prompt_still_counts(self):
        html = """
        <html>
          <body>
            <div>Nur fuer Abonnenten.</div>
            <div>Jetzt abonnieren, um weiterzulesen und Zugriff auf den vollstaendigen Artikel zu erhalten.</div>
          </body>
        </html>
        """.lower()

        is_paywalled, score, reasons = _is_paywalled_by_signals(html)

        self.assertTrue(is_paywalled)
        self.assertGreaterEqual(score, 60)
        self.assertTrue(any(reason.startswith("strong:") for reason in reasons))


if __name__ == "__main__":
    unittest.main()