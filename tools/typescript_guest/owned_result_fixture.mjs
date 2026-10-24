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
    const entries=body?.filter(node=>node.type==='VariableDeclaration').flatMap(node=>node.declarations)
      .filter(node=>node.id?.name==='started'&&node.init?.type==='AwaitExpression'&&
        node.init.argument.type==='CallExpression'&&node.init.argument.arguments.length===0&&
        node.init.argument.callee.type==='MemberExpression'&&!node.init.argument.callee.computed&&
        node.init.argument.callee.object.type==='Identifier'&&node.init.argument.callee.object.name==='task'&&
        node.init.argument.callee.property.type==='Identifier'&&node.init.argument.callee.property.name==='enter');
    const invocations=[];
    function walk(node){
      if(!node||typeof node!=='object')return;
      if(Array.isArray(node)){for(const child of node)walk(child);return;}
      if(node.type==='CallExpression'&&node.callee.type==='Identifier'&&node.callee.name==='__lsfAwaitImport')invocations.push(node);
      for(const value of Object.values(node))if(value&&typeof value==='object')walk(value);
    }
    walk(body);
    if(entries?.length!==1||invocations.length!==1||entries[0].end>=invocations[0].start)fail();
    // The ordinary helper returns the REAL native carrier. Register our real
    // reaction before returning it to the metadata await. FIFO Promise jobs
    // place cancellation after actual Returned/lowering and before typed lift.
    // No status/buffer write or runtime dispatch hook supplies the result.
    const actual=source.slice(call.start,call.end);
    edits.push({start:call.start,end:call.end,text:`{
      const carrier=${actual};
      const context=__ownedFixtureContext;
      if(!context||context.alias!==${JSON.stringify(alias)}||!context.operation)throw Error('owned-fixture-operation-not-armed');
      if(context.cancelMode===1)carrier.then(()=>{context.operation.cancel();},()=>{});
      else if(context.cancelMode===2)context.operation.cancel();
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
