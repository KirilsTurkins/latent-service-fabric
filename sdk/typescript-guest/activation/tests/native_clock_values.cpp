// Exact selected per-Store math; no host clock or engine qualification claim.
#include "../clock_values.h"
#include <cstdio>
#include <cstring>
#include <limits>
using namespace lsf::typescript::activation;
int main(int argc,char** argv) {
  if (argc!=2) return 2;
  const auto* selected=argv[1];ClockValues values;double elapsed=0,epoch=0;int status=1;
  if (!std::strcmp(selected,"no-compiler-origin")) status=!values.sampled()?0:1;
  else if (!std::strcmp(selected,"first-actual-sample"))
    status=values.performance(50000000,1700000000000,elapsed,epoch)&&elapsed==0&&epoch==1700000000000?0:1;
  else if (!std::strcmp(selected,"actual-monotonic-elapsed")) {
    if (!values.performance(50000000,1000,elapsed,epoch)) return 3;
    status=values.performance(51250000,0,elapsed,epoch)&&elapsed==1.25&&epoch==1000?0:1;
  } else if (!std::strcmp(selected,"wall-adjustment-does-not-reset-origin")) {
    if (!values.performance(50,1000,elapsed,epoch)) return 3;
    status=values.performance(1000050,9999999,elapsed,epoch)&&elapsed==1&&epoch==1000?0:1;
  } else if (!std::strcmp(selected,"backward-monotonic-rejected")) {
    if (!values.performance(100,1000,elapsed,epoch)) return 3;
    status=!values.performance(99,1000,elapsed,epoch)?0:1;
  } else if (!std::strcmp(selected,"Date-overflow-before-state-change"))
    status=!values.performance(100,ClockValues::maximum_date_millis+1,elapsed,epoch)&&!values.sampled()?0:1;
  else if (!std::strcmp(selected,"fresh-Store-origin-independent")) {
    ClockValues other;
    if (!values.performance(100,1000,elapsed,epoch)) return 3;
    status=other.performance(900,2000,elapsed,epoch)&&epoch==2000&&elapsed==0?0:1;
  } else if (!std::strcmp(selected,"Date-maximum-exact-and-overflow-rejected")) {
    double wall=0;
    status=ClockValues::wall(ClockValues::maximum_date_millis,wall)&&wall==8640000000000000.0&&
           !ClockValues::wall(std::numeric_limits<uint64_t>::max(),wall)?0:1;
  } else return 4;
  std::printf("{\"case\":\"%s\",\"status\":%d,\"sampled\":%s}\n",selected,status,values.sampled()?"true":"false");
  return status;
}
