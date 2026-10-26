package org.thevoid.port;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/** The game's files the layer writes before the game starts (the
 *  configurator's rcfg.xml and scfg.xml in the profile, the game's
 *  settings) and the release's key bindings (data/actions.xml). */
final class Profile {
    private Profile() { }

    /** Move the old shared profile into the chosen installation; existing destination files win. */
    static void migrate(File from, File to) throws IOException {
        if (java.nio.file.Files.isSymbolicLink(from.toPath()) || java.nio.file.Files.isSymbolicLink(to.toPath()))
            throw new IOException("linked profile path: " + from + " -> " + to);
        from = from.getCanonicalFile();
        to = to.getCanonicalFile();
        if (from.equals(to) || !from.exists()) return;
        if (to.toPath().startsWith(from.toPath()) || from.toPath().startsWith(to.toPath()))
            throw new IOException("overlapping profile folders: " + from + " -> " + to);
        if (!to.exists() && from.renameTo(to)) return;
        if (from.isDirectory()) {
            if (!to.isDirectory() && !to.mkdirs()) throw new IOException("cannot create " + to);
            File[] files = from.listFiles();
            if (files == null) throw new IOException("cannot read " + from);
            for (File file : files) migrate(file, new File(to, file.getName()));
            from.delete();   // Conflicting originals stay as a backup, never replace the selected profile.
        } else if (!to.exists()) {
            java.nio.file.Files.move(from.toPath(), to.toPath());
        }
    }

    /** The renderer's configuration as Config.exe writes it (RendererD3D reads
     *  an HDR node: absent off, simple="1" simplified, without it full). */
    static void writeRenderer(File dir, int width, int height, Settings s) {
        StringBuilder x = new StringBuilder("﻿<?xml version=\"1.0\" encoding=\"utf-8\" ?>\r\n<Renderer>\r\n");
        x.append("\t<Width>").append(width).append("</Width>\r\n");
        x.append("\t<Height>").append(height).append("</Height>\r\n");
        if (s.hdr != 0) x.append(s.hdr == 1 ? "\t<HDR simple=\"1\" />\r\n" : "\t<HDR />\r\n");
        // Explicit original strategies keep every quality choice in the two
        // shipped SM3 material families, including simplified HDR.
        x.append("\t<Profile force=\"").append(s.hdr == 0 ? "fx_3_0" : s.hdr == 1 ? "fx_3_0hs" : "fx_3_0hf")
            .append("\" />\r\n");
        x.append("\t<RefreshRate>0</RefreshRate>\r\n\t<Antialiasing>0</Antialiasing>\r\n");
        x.append("\t<Anisotropy>").append(s.anisotropy).append("</Anisotropy>\r\n");
        x.append("\t<LightmapQuality>").append(s.lightmapQuality).append("</LightmapQuality>\r\n");
        x.append("\t<TextureQuality>").append(s.textureQuality).append("</TextureQuality>\r\n</Renderer>\r\n");
        write(new File(dir, "rcfg.xml"), x.toString());
    }

    static void writeSound(File dir, Settings s) {
        write(new File(dir, "scfg.xml"), "﻿<?xml version=\"1.0\" encoding=\"utf-8\" ?>\r\n<Sound>\r\n\t<Quality rate=\""
            + (s.soundRate == 22 ? 22 : 44) + "\" />\r\n</Sound>\r\n");
    }

    /** MouseSensitivity 1 once, whatever the release ships (the Russian
     *  release has 0.19): the player's later choice in the options stays. */
    static void defaultSensitivity(File settingsXml) {
        String xml = GameActivity.Release.read(settingsXml);
        if (xml.isEmpty()) return;
        int at = xml.indexOf("\"MouseSensitivity\"");
        String out;
        if (at < 0) {
            int end = xml.lastIndexOf("</Settings>");
            if (end < 0) return;
            out = xml.substring(0, end) + "  <prop name=\"MouseSensitivity\" value=\"1\" />\r\n" + xml.substring(end);
        } else {
            int v = xml.indexOf("value=\"", at);
            int close = v < 0 ? -1 : xml.indexOf('"', v + 7);
            if (close < 0) return;
            out = xml.substring(0, v + 7) + "1" + xml.substring(close);
        }
        write(settingsXml, out);
    }

    /** The game keeps its settings in data\settings.xml (it reads the
     *  profile's file only where the release has none, and the releases ship
     *  one) and writes them there as the options change: android/host/files.c
     *  serves the player's own copy (<data>/overrides/settings.xml), made
     *  from the release's file once. The game knows only the props the file
     *  has: the port's are added where missing, with the layer's values; the
     *  values the game wrote stay. */
    static void ensureSettings(File releaseSettings, File settingsXml, Map<String, String> props) {
        String old = GameActivity.Release.read(settingsXml);
        String xml = old.lastIndexOf("</Settings>") >= 0 ? old : GameActivity.Release.read(releaseSettings);
        int end = xml.lastIndexOf("</Settings>");
        if (end < 0) return;
        StringBuilder added = new StringBuilder();
        for (Map.Entry<String, String> e : props.entrySet())
            if (xml.indexOf("\"" + e.getKey() + "\"") < 0)
                added.append("\t<prop name=\"").append(e.getKey()).append("\" value=\"").append(e.getValue()).append("\" />\r\n");
        String out = xml.substring(0, end) + added + xml.substring(end);
        if (!out.equals(old)) {
            settingsXml.getParentFile().mkdirs();
            write(settingsXml, out);
        }
    }

    /** A prop of the game's settings.xml ("" if absent). */
    static String prop(String xml, String name) {
        int at = xml.indexOf("\"" + name + "\"");
        if (at < 0) return "";
        int v = xml.indexOf("value=\"", at);
        int end = v < 0 ? -1 : xml.indexOf('"', v + 7);
        return end < 0 ? "" : xml.substring(v + 7, end);
    }

    /** Sets props of the game's settings.xml (the file is created if missing),
     *  only before the game runs: the game keeps its Settings in memory and
     *  writes them back when the options change. */
    static void setProps(File settingsXml, Map<String, String> props) {
        String xml = GameActivity.Release.read(settingsXml);
        if (xml.isEmpty() || xml.lastIndexOf("</Settings>") < 0)
            xml = "<?xml version=\"1.0\" encoding=\"utf-8\" ?>\r\n<Settings>\r\n</Settings>\r\n";
        for (Map.Entry<String, String> e : props.entrySet()) {
            String key = "\"" + e.getKey() + "\"";
            int at = xml.indexOf(key);
            if (at < 0) {
                int end = xml.lastIndexOf("</Settings>");
                xml = xml.substring(0, end) + "  <prop name=\"" + e.getKey() + "\" value=\"" + e.getValue() + "\" />\r\n"
                    + xml.substring(end);
            } else {
                int v = xml.indexOf("value=\"", at);
                int close = v < 0 ? -1 : xml.indexOf('"', v + 7);
                if (close >= 0) xml = xml.substring(0, v + 7) + e.getValue() + xml.substring(close);
            }
        }
        write(settingsXml, xml);
    }

    /** Action name -> scan code (Keys.MOUSE_RIGHT for the right button) of
     *  the bindings in effect: the first handler of each action, as the
     *  player rebound it in the options (the game's Settings keep
     *  "action_<name>" = "key, key") or else as the actions file has it. */
    static Map<String, Integer> actions(File actionsXml, File settingsXml) {
        Map<String, Integer> map = actions(actionsXml);
        String xml = GameActivity.Release.read(settingsXml);
        for (String name : new java.util.ArrayList<>(map.keySet())) {
            String handlers = prop(xml, "action_" + name);
            if (handlers.isEmpty()) continue;
            int comma = handlers.indexOf(',');
            int code = Keys.forName((comma >= 0 ? handlers.substring(0, comma) : handlers).trim());
            if (code != 0) map.put(name, code);
        }
        return map;
    }

    static Map<String, Integer> actions(File actionsXml) {
        Map<String, Integer> map = new HashMap<>();
        String xml = GameActivity.Release.read(actionsXml);
        int at = 0;
        while ((at = xml.indexOf("<Action", at)) >= 0) {
            int end = xml.indexOf('>', at);
            if (end < 0) break;
            String tag = xml.substring(at, end);
            String name = GameActivity.Release.attribute(tag, "name");
            String handler = GameActivity.Release.attribute(tag, "handler");
            int comma = handler.indexOf(',');
            if (comma >= 0) handler = handler.substring(0, comma);
            int code = Keys.forName(handler.trim());
            if (!name.isEmpty() && code != 0) map.put(name, code);
            at = end;
        }
        return map;
    }

    private static void write(File f, String text) {
        try (FileOutputStream out = new FileOutputStream(f)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            android.util.Log.w("TheVoid", "cannot write " + f + ": " + e);
        }
    }
}
