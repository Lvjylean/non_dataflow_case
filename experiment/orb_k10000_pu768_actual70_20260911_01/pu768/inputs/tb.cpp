#include "xf_bfmatcher_accel_config.h"
#include <cstdio>
#include <vector>
#include <cstdint>
extern "C" void bfmatcher_accel(ap_uint<256>*,ap_uint<256>*,ap_int<16>*,uint32_t,uint32_t,float);
static uint64_t state=0x123456789abcdefULL;
uint64_t rand64(){state^=state<<13;state^=state>>7;state^=state<<17;return state;}
ap_uint<256> descriptor(){ap_uint<256>x=0;for(int w=0;w<4;w++)x.range(w*64+63,w*64)=rand64();return x;}
int distance(ap_uint<256>a,ap_uint<256>b){int d=0;for(int w=0;w<4;w++){uint64_t x=a.range(w*64+63,w*64).to_uint64()^b.range(w*64+63,w*64).to_uint64();d+=__builtin_popcountll(x);}return d;}
int main(){
  const int cases[][2]={{0,33},{1,33},{767,33},{768,33},{769,33},{10000,33},{3,10000},{2000,2000}};
  for(auto &c:cases){int nq=c[0],nt=c[1];std::vector<ap_uint<256>> q(MAX_KEYPOINTS),t(MAX_KEYPOINTS);std::vector<ap_int<16>> out(MAX_KEYPOINTS);
    for(int j=0;j<nt;j++)t[j]=descriptor();
    for(int i=0;i<nq;i++){q[i]=(i%3)?t[(i*7)%nt]:descriptor();if(i%5==0)q[i]^=ap_uint<256>(7);}
    bfmatcher_accel(q.data(),t.data(),out.data(),nq,nt,0.75f);
    for(int i=0;i<nq;i++){int best=511,second=511,index=0;for(int j=0;j<nt;j++){int d=distance(q[i],t[j]);if(d<best){second=best;best=d;index=j;}else if(d<second)second=d;}int want=(float(best)<0.75f*float(second))?index:-1;if(out[i].to_int()!=want){std::printf("FAIL q=%d t=%d i=%d got=%d expected=%d\n",nq,nt,i,out[i].to_int(),want);return 1;}}
    std::printf("PASS q=%d t=%d\n",nq,nt);
  }
  std::puts("ALL_FUNCTIONAL_CASES_PASS");return 0;
}
