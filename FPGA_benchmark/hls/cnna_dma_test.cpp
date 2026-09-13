#include <ap_int.h>
#include <ap_axi_sdata.h>
#include <hls_stream.h>
typedef ap_uint<256> record_t;
typedef ap_axiu<128,0,0,0> packet128_t;
typedef ap_axiu<64,0,0,0> packet64_t;
extern "C" void cnna_dma(const record_t*,const record_t*,const record_t*,const record_t*,record_t*,unsigned,unsigned,unsigned,unsigned,unsigned,hls::stream<packet128_t>&,hls::stream<packet128_t>&,hls::stream<packet128_t>&,hls::stream<packet64_t>&,hls::stream<packet128_t>&);
#include <cassert>
int main() {
  record_t x[3],w[3],b[3],c[3],y[3];
  hls::stream<packet128_t> sx,sw,sb,sy;
  hls::stream<packet64_t> sc;
  for (int i=0;i<3;i++) {
    x[i]=w[i]=b[i]=c[i]=0;
    x[i].range(127,0)=i+7; x[i].range(143,128)=0xFFFF; x[i][144]=(i==2);
    w[i]=x[i]; w[i].range(127,0)=i+100;
    b[i]=x[i]; b[i].range(127,0)=i+200;
    c[i].range(63,0)=i+9;
    c[i].range(71,64)=0x7F; c[i][72]=(i==2);
    packet128_t p; p.data=i+42; p.keep=0x00FF; p.strb=p.keep; p.last=(i==2); sy.write(p);
  }
  cnna_dma(x,w,b,c,y,3,3,3,3,3,sx,sw,sb,sc,sy);
  for(int i=0;i<3;i++) {
    packet128_t a=sx.read(),d=sw.read(),e=sb.read(); packet64_t f=sc.read();
    assert(a.data==i+7 && d.data==i+100 && e.data==i+200);
    assert(a.keep==0xFFFF && a.last==(i==2));
    assert(f.data==i+9 && f.keep==0x7F && f.last==(i==2));
    assert(y[i].range(127,0)==i+42 && y[i].range(143,128)==0x00FF && y[i][144]==(i==2));
  }
  cnna_dma(x,w,b,c,y,0,0,0,0,0,sx,sw,sb,sc,sy);
  assert(sx.empty() && sw.empty() && sb.empty() && sc.empty() && sy.empty());
  return 0;
}
