using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.Nfc;
using Android.OS;
using Android.Views;
using Android.Webkit;
using Android.Widget;

namespace LaNubeKiosk;

[Activity(
    Label = "@string/app_name",
    MainLauncher = true,
    LaunchMode = LaunchMode.SingleTop,
    ConfigurationChanges = ConfigChanges.Orientation | ConfigChanges.KeyboardHidden | ConfigChanges.ScreenSize)]
public class MainActivity : Activity
{
    private WebView webView = null!;
    private NfcAdapter? nfcAdapter;
    private const string KioskUrl = "https://lanube.uno";

    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        RequestWindowFeature(WindowFeatures.NoTitle);

        webView = new WebView(this);
        SetContentView(webView);

        CookieManager.Instance?.SetAcceptCookie(true);
        CookieManager.Instance?.SetAcceptThirdPartyCookies(webView, true);

        webView.Settings!.JavaScriptEnabled = true;
        webView.Settings.DomStorageEnabled = true;
        webView.Settings.SetSupportZoom(false);
        webView.Settings.BuiltInZoomControls = false;
        webView.Settings.DisplayZoomControls = false;
        webView.Settings.UseWideViewPort = true;
        webView.Settings.LoadWithOverviewMode = true;
        webView.SetWebViewClient(new WebViewClient());
        webView.SetWebChromeClient(new WebChromeClient());

        // Load debug start page to confirm version
        webView.LoadData(
            "<html><body style='font-size:28px;padding:30px;font-family:sans-serif;background:#0f172a;color:white'>" +
            "<h2 style='color:#38bdf8'>La Nube Kiosk v6</h2>" +
            "<p>NFC: " + (NfcAdapter.GetDefaultAdapter(this) != null ? "✅ disponible" : "❌ no disponible") + "</p>" +
            "<p style='color:#94a3b8'>Acercá una tarjeta para ver el UID...</p>" +
            "</body></html>",
            "text/html", "utf-8");

        nfcAdapter = NfcAdapter.GetDefaultAdapter(this);
        HideSystemUI();
    }

    public override void OnWindowFocusChanged(bool hasFocus)
    {
        base.OnWindowFocusChanged(hasFocus);
        if (hasFocus) HideSystemUI();
    }

    private void HideSystemUI()
    {
#pragma warning disable CA1416, CS0618
        Window!.DecorView.SystemUiVisibility = (StatusBarVisibility)(
            (int)SystemUiFlags.Fullscreen |
            (int)SystemUiFlags.HideNavigation |
            (int)SystemUiFlags.ImmersiveSticky |
            (int)SystemUiFlags.LayoutStable |
            (int)SystemUiFlags.LayoutHideNavigation |
            (int)SystemUiFlags.LayoutFullscreen);
#pragma warning restore CA1416, CS0618
    }

    protected override void OnResume()
    {
        base.OnResume();
        if (nfcAdapter == null) return;
        var intent = new Intent(this, typeof(MainActivity));
        intent.AddFlags(ActivityFlags.SingleTop);
#pragma warning disable CA1416
        var flags = Build.VERSION.SdkInt >= BuildVersionCodes.S
            ? PendingIntentFlags.Mutable
            : (PendingIntentFlags)0;
#pragma warning restore CA1416
        var pending = PendingIntent.GetActivity(this, 0, intent, flags);
        nfcAdapter.EnableForegroundDispatch(this, pending, null, null);
    }

    protected override void OnPause()
    {
        base.OnPause();
        nfcAdapter?.DisableForegroundDispatch(this);
    }

    protected override void OnNewIntent(Intent? intent)
    {
        base.OnNewIntent(intent);
        if (intent == null) return;

        try
        {
#pragma warning disable CA1422
            var tagObj = intent.GetParcelableExtra(NfcAdapter.ExtraTag);
#pragma warning restore CA1422

            if (tagObj is not Android.Nfc.Tag tag)
            {
                ShowHtml("Sin tag", "El intent no trajo EXTRA_TAG.", "", "");
                return;
            }

            var id = tag.GetId();
            if (id == null || id.Length == 0)
            {
                ShowHtml("Sin ID", "GetId() devolvió vacío.", "", "");
                return;
            }

            var raw = BitConverter.ToString(id).Replace("-", "");

            Array.Reverse(id);
            var sb = new System.Text.StringBuilder();
            foreach (var b in id)
                sb.Append(((b & 0x0F) << 4 | (b >> 4)).ToString("X2"));
            var uid = sb.ToString();

            var match = uid == "53A3A343300001" ? "SÍ COINCIDE ✅" : "NO coincide ❌";
            ShowHtml(raw, uid, match, id.Length.ToString());
        }
        catch (Exception ex)
        {
            ShowHtml("EXCEPCIÓN", ex.Message, "", "");
        }
    }

    private void ShowHtml(string raw, string uid, string match, string bytes)
    {
        RunOnUiThread(() =>
            webView.LoadData(
                "<html><body style='font-size:26px;padding:30px;font-family:monospace;background:#0f172a;color:white'>" +
                "<h2 style='color:#38bdf8'>La Nube Kiosk v6 — NFC debug</h2>" +
                $"<p><b>RAW (Android):</b><br><span style='color:#fbbf24'>{raw}</span></p>" +
                $"<p><b>UID calculado:</b><br><span style='color:#34d399'>{uid}</span></p>" +
                $"<p><b>Windows esperado:</b><br><span style='color:#94a3b8'>53A3A343300001</span></p>" +
                $"<p style='font-size:30px'>{match}</p>" +
                "<br><button onclick=\"window.location='https://lanube.uno'\" " +
                "style='font-size:22px;padding:12px 24px;border-radius:8px;background:#1e3a5f;color:white;border:none'>" +
                "Ir al kiosko</button>" +
                "</body></html>",
                "text/html", "utf-8"));
    }

    public override void OnBackPressed()
    {
        if (webView.CanGoBack()) webView.GoBack();
    }
}
