package uno.lanube.nfctest;

import com.droidlogic.app.tv.TvControlManager;

public class NfcBridge {

    public static void i2cInit(int bus) {
        TvControlManager.getInstance().i2c_init(bus);
    }

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
