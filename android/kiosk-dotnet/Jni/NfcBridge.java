package uno.lanube.kiosk;

import com.droidlogic.app.tv.TvControlManager;

/**
 * Bridge Java para llamar i2c_read desde C#.
 * Maneja el int[] internamente y devuelve el UID como String.
 */
public class NfcBridge {

    public static void i2cInit(int bus) {
        TvControlManager.getInstance().i2c_init(bus);
    }

    /**
     * Lee una tarjeta NFC.
     * @return UID en hex mayuscula (ej. "D779CD0A") o "" si no hay tarjeta.
     */
    public static String readUid(int bus, int addr, int reg) {
        int[] buf = new int[6];
        int ret = TvControlManager.getInstance().i2c_read(bus, addr, reg, 5, buf);
        if (ret != 0) return "";
        StringBuilder sb = new StringBuilder(8);
        for (int i = 0; i < 4; i++) {
            sb.append(String.format("%02X", buf[i] & 0xFF));
        }
        String uid = sb.toString();
        return uid.equals("00000000") ? "" : uid;
    }
}
