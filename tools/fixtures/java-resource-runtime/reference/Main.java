// Host reference only: controlled correlated-byte sink; never packaged into the guest.
import java.io.*;
import java.nio.charset.StandardCharsets;
import outside.resourceruntime.Library;
public final class Main {
 static final class Budget extends OutputStream {
  final int base; int bytes; int accepted; int rejected;
  Budget(int base) { this.base=base; }
  public void write(int value) throws IOException { write(new byte[]{(byte)value},0,1); }
  public synchronized void write(byte[] data,int offset,int count) throws IOException {
   if (count==0) return;
   int encoded=base+count;
   for(int i=offset;i<offset+count;i++) if(data[i]==10||data[i]==13||data[i]==34||data[i]==92) encoded++;
   if(encoded>256-bytes) { rejected++; throw new IOException("controlled-correlated-log-budget"); }
   accepted++;bytes+=encoded;
  }
 }
 public static void main(String[] args) {
  PrintStream original=System.out;Budget budget=new Budget(Integer.parseInt(args[1]));
  System.setOut(new PrintStream(budget,false,StandardCharsets.UTF_8));
  String result="";String error="none";
  try { result=Library.run(args[0]); }
  catch(Throwable failure) { error=failure.getClass().getName(); }
  original.println("{\"error\":\""+error+"\",\"result\":\""+result+"\",\"accepted\":"+budget.accepted+",\"rejected\":"+budget.rejected+",\"bytes\":"+budget.bytes+"}");
  System.exit(error.equals("none")?0:3);
 }
}
