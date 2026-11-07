package org.immensiva.monitorprobe;

/** Uses the pinned scrcpy display-power implementation from its server jar. */
public final class DisplayPower {
    public static void main(String[] args) throws Exception {
        if (args.length != 1 || (!args[0].equals("on") && !args[0].equals("off"))) {
            throw new IllegalArgumentException("Expected on or off");
        }
        Class<?> device = Class.forName("com.genymobile.scrcpy.device.Device");
        boolean success = (Boolean) device.getMethod(
            "setDisplayPower", int.class, boolean.class).invoke(null, 0, args[0].equals("on"));
        if (!success) throw new IllegalStateException("Display power command failed");
        System.out.println("IMMENSIVA_DISPLAY " + args[0]);
        System.exit(0);
    }
}
