// Compiler-only finite Component Model fixture. Never installed by the normal
// SDK compiler and never accepts application binding names or numeric IDs.
import {borrowReleaseHandoff} from './import_cancellation.mjs';

export const ownFixtureSelection = Object.freeze([
  Object.freeze({binding:'import_tests_owned_result_provider_1_0_0$takeConnection',alias:'connection'}),
  Object.freeze({binding:'import_tests_owned_result_provider_1_0_0$takeChunk',alias:'chunk'}),
  Object.freeze({binding:'import_tests_owned_result_provider_1_0_0$nested',alias:'nested'}),
]);

export function ownedResultFixtureBindings(source,parse,backing=false) {
  const fail=()=>{throw Error('owned-result-fixture-binding-shape-drift');};
  if(typeof backing!=='boolean')fail();
  const selection=backing ? [...ownFixtureSelection,
    {binding:'import_tests_owned_result_provider_1_0_0$backing',alias:'backing'}] : ownFixtureSelection;
  if(source.includes('__ownedFixture')||source.includes('tests:owned-result/control@1.0.0'))fail();
  source=borrowReleaseHandoff(source,parse,selection);
  const tree=parse(source,{ecmaVersion:'latest',sourceType:'module'});
  const edits=[];
  for(const {binding,alias} of selection) {
    const functions=tree.body.filter(node=>node.type==='FunctionDeclaration'&&node.id?.name===binding);
    if(functions.length!==1)fail();
    const fn=functions[0];
    const helpers=fn.body.body.filter(node=>node.type==='VariableDeclaration'&&
      node.declarations.length===1&&node.declarations[0].id.name==='__lsfAwaitImport');
    if(helpers.length!==1)fail();
    const arrow=helpers[0].declarations[0].init,call=arrow?.body;
    if(arrow?.type!=='ArrowFunctionExpression'||arrow.async||call?.type!=='CallExpression'||
       call.callee.type!=='Identifier'||call.callee.name!=='$'+binding)fail();
    const body=fn.body.body.find(node=>node.type==='TryStatement')?.block.body;
    const invocations=[],awaits=[];let legacy=false;
    function walk(node){
      if(!node||typeof node!=='object')return;
      if(Array.isArray(node)){for(const child of node)walk(child);return;}
      if(node.type==='CallExpression'&&node.callee.type==='Identifier'&&node.callee.name==='__lsfAwaitImport')invocations.push(node);
      if(node.type==='AwaitExpression')awaits.push(node);
      if(node.type==='CallExpression'&&
        (node.callee.type==='Identifier'&&['createNewCurrentTask','_withGlobalCurrentTaskMetaAsync'].includes(node.callee.name)||
         node.callee.type==='MemberExpression'&&node.callee.object.type==='Identifier'&&node.callee.object.name==='task'))legacy=true;
      for(const value of Object.values(node))if(value&&typeof value==='object')walk(value);
    }
    walk(body);
    const transfers=body?.filter(node=>node.type==='ExpressionStatement'&&
      node.expression.type==='AssignmentExpression'&&node.expression.operator==='='&&
      node.expression.left.type==='Identifier'&&node.expression.left.name==='ret'&&
      node.expression.right.type==='CallExpression'&&node.expression.right.arguments.length===1&&
      node.expression.right.callee.type==='MemberExpression'&&!node.expression.right.callee.computed&&
      node.expression.right.callee.object.type==='Identifier'&&node.expression.right.callee.object.name==='__lsfImports'&&
      node.expression.right.callee.property.type==='Identifier'&&node.expression.right.callee.property.name==='lift');
    const awaited=transfers?.[0]?.expression.right.arguments[0];
    const arm=body?.[0]?.expression;
    if(legacy||transfers?.length!==1||invocations.length!==1||awaits.length!==1||awaited!==awaits[0]||
       awaited.argument!==invocations[0]||arm?.type!=='CallExpression'||arm.callee.type!=='Identifier'||
       arm.callee.name!=='__lsfBorrowArm')fail();
    // The ordinary helper returns the REAL native carrier. Register our real
    // reaction before returning it to the metadata await. FIFO Promise jobs
    // place cancellation after actual Returned/lowering and before typed lift.
    // No status/buffer write or runtime dispatch hook supplies the result.
    const actual=source.slice(call.start,call.end);
    edits.push({start:call.start,end:call.end,text:`{
      const carrier=${actual};
      const context=__ownedFixtureContext;
      if(!context||context.alias!==${JSON.stringify(alias)})throw Error('owned-fixture-operation-not-armed');
      if(context.cancelMode===1)carrier.then(()=>{
        if(!context.operation)throw Error('owned-fixture-operation-not-armed');
        context.operation.cancel();
      },()=>{});
      return carrier;
    }`});
  }
  const bridges=tree.body.filter(node=>node.type==='VariableDeclaration'&&node.kind==='const'&&
    node.declarations.some(item=>item.id.name==='__lsfBorrowCalls'));
  if(bridges.length!==1)fail();
  const bridge=bridges[0];
  edits.push({start:bridge.end,end:bridge.end,text:`
let __ownedFixtureContext=null;
defineBuiltinModule('tests:owned-result/control@1.0.0',{
  dispose(value){value[symbolDispose]();},
  ${backing ? 'backingFreeCount(){return __lsfImports.backingFreeCount();},' : ''}
  start(alias,mode,cancelMode){
    if(!${JSON.stringify(selection.map(item=>item.alias))}.includes(alias)||![0,1,2].includes(cancelMode)||!Number.isInteger(mode)||mode<0||mode>(alias==='backing'?7:5))throw Error('owned-fixture-closed-input');
    const context={alias,cancelMode,operation:null};
    __ownedFixtureContext=context;
    const operation=__lsfBorrowCalls[alias](mode);
    context.operation=operation;
    // Native-only entry has already made its actual first host poll before
    // returning this operation. Cancel on the SAME stack before await/lift.
    if(cancelMode===2)operation.cancel();
    return operation;
  }
});
`});
  edits.sort((a,b)=>b.start-a.start);
  let end=source.length;
  for(const edit of edits){if(edit.end>end)fail();source=source.slice(0,edit.start)+edit.text+source.slice(edit.end);end=edit.start;}
  parse(source,{ecmaVersion:'latest',sourceType:'module'});
  return source;
}
