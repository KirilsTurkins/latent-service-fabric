import java.io.File;
import java.lang.reflect.InvocationTargetException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Path;
import java.util.regex.Pattern;
/** Fresh private activation and ledger for each injected source case. */
public final class TimerStartAdmissionProjectionControl {
    public static void main(String[] args) throws Exception {
        String[] entries=System.getProperty("java.class.path").split(Pattern.quote(File.pathSeparator));
        URL[] urls=new URL[entries.length];
        for(int i=0;i<entries.length;i++)urls[i]=Path.of(entries[i]).toUri().toURL();
        String[] modes={"normal","refusal","lost-start","inflight-root","inflight-worker","same-work",
            "same-work-post-list","nested-distinct","overflow","settle-before-start","settle-refusal-retry",
            "settle-lost-ack","settle-refusal-reentry","allocation-root","lookup-root","preparation-root","preparation-same-work"};
        for(String mode:modes)try(var loader=new URLClassLoader(urls,ClassLoader.getPlatformClassLoader())) {
            try {Class.forName("TimerStartAdmissionControl",true,loader).getMethod("main",String[].class)
                .invoke(null,(Object)new String[]{mode});}
            catch(InvocationTargetException error) {
                if(error.getCause() instanceof Exception exception)throw exception;
                if(error.getCause() instanceof Error failure)throw failure;
                throw error;
            }
        }
        System.out.println("START_ADMISSION_PROJECTED PASS cases="+modes.length);
    }
}
