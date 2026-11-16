package dev.latent.guest;
import dev.latent.generated.Bindings;
public final class PageCheck {
 static void denied(Runnable r){try{r.run();throw new AssertionError("accepted");}catch(IllegalStateException expected){}}
 public static void main(String[] a){
  State.Query q=State.acquireQuery().value(); State.Page p=q.scan(new byte[0],1L,Option.none()).value(); Resource raw=Bindings.page;
  raw.borrow(); denied(p::close); denied(q::close); raw.releaseBorrow(); p.close(); q.close();
  q=State.acquireQuery().value(); p=q.scan(new byte[0],1L,Option.none()).value(); State.Query held=q; State.Page page=p;
  Wire.fail=true; denied(page::close); Wire.fail=false; denied(page::close); denied(held::close);
  System.out.println("page ownership checks passed");
 }}