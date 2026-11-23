package dev.latent.generated;
import dev.latent.guest.*;
public final class Bindings {
 public static LatentStateKeyValuePage page;
 public static class LatentStateKeyValuePage extends Resource { public LatentStateKeyValuePage(){super(1,1);} }
 public static class LatentStateKeyValueTransaction extends Resource { public LatentStateKeyValueTransaction(){super(2,2);} }
 public static class LatentStateKeyValueQueryView extends Resource { public LatentStateKeyValueQueryView(){super(3,3);} }
 public static class LatentStateKeyValueStateError {} public static class LatentStateKeyValueCommandInfo {} public static class LatentStateKeyValueVersionedValue {} public static class LatentStateKeyValueValue {} public static class LatentStateKeyValueViewIdentity {} public static class LatentStateKeyValuePageInfo {} public static class LatentStateKeyValueEntry {}
 public static class LatentStateKeyValue {
 public static Result<LatentStateKeyValueCommandInfo,LatentStateKeyValueStateError> info(LatentStateKeyValueTransaction x){return null;}
 public static Result<Option<LatentStateKeyValueVersionedValue>,LatentStateKeyValueStateError> get(LatentStateKeyValueTransaction x,byte[] y){return null;}
 public static Result<Unit,LatentStateKeyValueStateError> put(LatentStateKeyValueTransaction x,byte[] y,LatentStateKeyValueValue z){return null;}
 public static Result<Unit,LatentStateKeyValueStateError> delete(LatentStateKeyValueTransaction x,byte[] y){return null;}
 public static Result<LatentStateKeyValuePage,LatentStateKeyValueStateError> scan(LatentStateKeyValueTransaction x,byte[] y,Long z,Option<byte[]> c){return null;}
 public static Result<LatentStateKeyValueViewIdentity,LatentStateKeyValueStateError> queryInfo(LatentStateKeyValueQueryView x){return null;}
 public static Result<Option<LatentStateKeyValueVersionedValue>,LatentStateKeyValueStateError> getQuery(LatentStateKeyValueQueryView x,byte[] y){return null;}
 public static Result<LatentStateKeyValuePage,LatentStateKeyValueStateError> scanQuery(LatentStateKeyValueQueryView x,byte[] y,Long z,Option<byte[]> c){page=new LatentStateKeyValuePage();return Result.ok(page);}
 public static Result<LatentStateKeyValuePageInfo,LatentStateKeyValueStateError> describePage(LatentStateKeyValuePage x){return null;}
 public static Result<Option<LatentStateKeyValueEntry>,LatentStateKeyValueStateError> pageNext(LatentStateKeyValuePage x){return null;}
 public static Result<LatentStateKeyValueTransaction,LatentStateKeyValueStateError> acquireCommand(){return null;}
 public static Result<LatentStateKeyValueQueryView,LatentStateKeyValueStateError> acquireQuery(){return Result.ok(new LatentStateKeyValueQueryView());}
 }}