package org.thevoid.port;

import android.util.SparseIntArray;
import android.view.KeyEvent;

/** Hardware keyboard keys as the original DirectInput scan codes. */
final class Keys {
    static final int MOUSE_LEFT = -1;
    static final int MOUSE_RIGHT = -2;   /* not a key: the right mouse button */
    private static final SparseIntArray DIK = new SparseIntArray();

    static {
        int[] letters = {0x1E, 0x30, 0x2E, 0x20, 0x12, 0x21, 0x22, 0x23, 0x17, 0x24, 0x25, 0x26, 0x32,
                         0x31, 0x18, 0x19, 0x10, 0x13, 0x1F, 0x14, 0x16, 0x2F, 0x11, 0x2D, 0x15, 0x2C};
        for (int i = 0; i < 26; ++i) DIK.put(KeyEvent.KEYCODE_A + i, letters[i]);
        DIK.put(KeyEvent.KEYCODE_0, 0x0B);
        for (int i = 1; i <= 9; ++i) DIK.put(KeyEvent.KEYCODE_0 + i, 0x01 + i);
        int[] f = {0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x57, 0x58};
        for (int i = 0; i < 12; ++i) DIK.put(KeyEvent.KEYCODE_F1 + i, f[i]);
        int[][] other = {
            {KeyEvent.KEYCODE_SPACE, 0x39}, {KeyEvent.KEYCODE_ENTER, 0x1C}, {KeyEvent.KEYCODE_NUMPAD_ENTER, 0x1C},
            {KeyEvent.KEYCODE_ESCAPE, 0x01}, {KeyEvent.KEYCODE_TAB, 0x0F}, {KeyEvent.KEYCODE_DEL, 0x0E},
            {KeyEvent.KEYCODE_FORWARD_DEL, 0xD3}, {KeyEvent.KEYCODE_SHIFT_LEFT, 0x2A}, {KeyEvent.KEYCODE_SHIFT_RIGHT, 0x36},
            {KeyEvent.KEYCODE_CTRL_LEFT, 0x1D}, {KeyEvent.KEYCODE_CTRL_RIGHT, 0x9D}, {KeyEvent.KEYCODE_ALT_LEFT, 0x38},
            {KeyEvent.KEYCODE_ALT_RIGHT, 0xB8}, {KeyEvent.KEYCODE_DPAD_UP, 0xC8}, {KeyEvent.KEYCODE_DPAD_DOWN, 0xD0},
            {KeyEvent.KEYCODE_DPAD_LEFT, 0xCB}, {KeyEvent.KEYCODE_DPAD_RIGHT, 0xCD}, {KeyEvent.KEYCODE_GRAVE, 0x29},
            {KeyEvent.KEYCODE_MINUS, 0x0C}, {KeyEvent.KEYCODE_EQUALS, 0x0D}, {KeyEvent.KEYCODE_LEFT_BRACKET, 0x1A},
            {KeyEvent.KEYCODE_RIGHT_BRACKET, 0x1B}, {KeyEvent.KEYCODE_BACKSLASH, 0x2B}, {KeyEvent.KEYCODE_SEMICOLON, 0x27},
            {KeyEvent.KEYCODE_APOSTROPHE, 0x28}, {KeyEvent.KEYCODE_SLASH, 0x35}, {KeyEvent.KEYCODE_COMMA, 0x33},
            {KeyEvent.KEYCODE_PERIOD, 0x34}, {KeyEvent.KEYCODE_PAGE_UP, 0xC9}, {KeyEvent.KEYCODE_PAGE_DOWN, 0xD1},
            {KeyEvent.KEYCODE_MOVE_HOME, 0xC7}, {KeyEvent.KEYCODE_MOVE_END, 0xCF}, {KeyEvent.KEYCODE_INSERT, 0xD2},
            {KeyEvent.KEYCODE_CAPS_LOCK, 0x3A}, {KeyEvent.KEYCODE_NUM_LOCK, 0x45}, {KeyEvent.KEYCODE_SCROLL_LOCK, 0x46},
            {KeyEvent.KEYCODE_SYSRQ, 0xB7}, {KeyEvent.KEYCODE_BREAK, 0xC5},
            {KeyEvent.KEYCODE_NUMPAD_DIVIDE, 0xB5}, {KeyEvent.KEYCODE_NUMPAD_MULTIPLY, 0x37},
            {KeyEvent.KEYCODE_NUMPAD_SUBTRACT, 0x4A}, {KeyEvent.KEYCODE_NUMPAD_ADD, 0x4E},
            {KeyEvent.KEYCODE_NUMPAD_DOT, 0x53},
        };
        for (int[] o : other) DIK.put(o[0], o[1]);
        int[] numpad = {0x52, 0x4f, 0x50, 0x51, 0x4b, 0x4c, 0x4d, 0x47, 0x48, 0x49};
        for (int i = 0; i < numpad.length; ++i) DIK.put(KeyEvent.KEYCODE_NUMPAD_0 + i, numpad[i]);
    }

    private Keys() { }

    /** The scan code for an Android key code, MOUSE_RIGHT, or 0 if none. */
    static int dik(int keyCode) { return DIK.get(keyCode, 0); }

    /** The scan code for a key name of the game's actions.xml ("0", "pgup",
     *  "lshift", "f5", "rbutton" = MOUSE_RIGHT), or 0 if none. */
    static int forName(String name) {
        String n = name.toLowerCase(java.util.Locale.ROOT);
        if (n.length() == 1) {
            char c = n.charAt(0);
            if (c >= 'a' && c <= 'z') return DIK.get(KeyEvent.KEYCODE_A + (c - 'a'), 0);
            if (c >= '0' && c <= '9') return DIK.get(KeyEvent.KEYCODE_0 + (c - '0'), 0);
        }
        if (n.length() >= 2 && n.charAt(0) == 'f') {
            try {
                int f = Integer.parseInt(n.substring(1));
                if (f >= 1 && f <= 12) return DIK.get(KeyEvent.KEYCODE_F1 + f - 1, 0);
            } catch (NumberFormatException e) { /* not a function key */ }
        }
        switch (n) {
        case "space": return 0x39;
        case "escape": return 0x01;
        case "return": return 0x1C;
        case "tab": return 0x0F;
        case "back": return 0x0E;
        case "lshift": return 0x2A;
        case "rshift": return 0x36;
        case "lctrl": return 0x1D;
        case "rctrl": return 0x9D;
        case "lalt": return 0x38;
        case "ralt": return 0xB8;
        case "pgup": return 0xC9;
        case "pgdn": return 0xD1;
        case "home": return 0xC7;
        case "end": return 0xCF;
        case "insert": return 0xD2;
        case "delete": return 0xD3;
        case "up": return 0xC8;
        case "down": return 0xD0;
        case "left": return 0xCB;
        case "right": return 0xCD;
        case "rbutton": return MOUSE_RIGHT;
        case "lbutton": return MOUSE_LEFT;
        case "mbutton": return -3;
        default: return 0;
        }
    }
}
