#include <ap_int.h>
#include <ap_axi_sdata.h>
#include <hls_stream.h>

typedef ap_uint<256> record_t;
typedef ap_axiu<128, 0, 0, 0> packet128_t;
typedef ap_axiu<64, 0, 0, 0> packet64_t;

// Preserve packet payload, byte enables and end-of-packet in host memory.
static void send128(const record_t *src, unsigned n, hls::stream<packet128_t> &dst) {
  for (unsigned i=0; i<n; ++i) {
#pragma HLS PIPELINE II=1
    record_t r=src[i]; packet128_t p;
    p.data=r.range(127,0); p.keep=r.range(143,128);
    p.strb=p.keep; p.last=r[144]; dst.write(p);
  }
}
static void send64(const record_t *src, unsigned n, hls::stream<packet64_t> &dst) {
  for (unsigned i=0; i<n; ++i) {
#pragma HLS PIPELINE II=1
    record_t r=src[i]; packet64_t p;
    p.data=r.range(63,0); p.keep=r.range(71,64);
    p.strb=p.keep; p.last=r[72]; dst.write(p);
  }
}
static void recv128(hls::stream<packet128_t> &src, record_t *dst, unsigned n) {
  for (unsigned i=0; i<n; ++i) {
#pragma HLS PIPELINE II=1
    packet128_t p=src.read(); record_t r=0;
    r.range(127,0)=p.data; r.range(143,128)=p.keep; r[144]=p.last;
    dst[i]=r;
  }
}
extern "C" void cnna_dma(const record_t *x, const record_t *w, const record_t *buf,
 const record_t *ctrl, record_t *y, unsigned nx, unsigned nw, unsigned nb,
 unsigned nc, unsigned ny, hls::stream<packet128_t> &sx,
 hls::stream<packet128_t> &sw, hls::stream<packet128_t> &sb,
 hls::stream<packet64_t> &sc, hls::stream<packet128_t> &sy) {
#pragma HLS INTERFACE m_axi port=x offset=slave bundle=mx
#pragma HLS INTERFACE m_axi port=w offset=slave bundle=mw
#pragma HLS INTERFACE m_axi port=buf offset=slave bundle=mb
#pragma HLS INTERFACE m_axi port=ctrl offset=slave bundle=mc
#pragma HLS INTERFACE m_axi port=y offset=slave bundle=my
#pragma HLS INTERFACE s_axilite port=x bundle=control
#pragma HLS INTERFACE s_axilite port=w bundle=control
#pragma HLS INTERFACE s_axilite port=buf bundle=control
#pragma HLS INTERFACE s_axilite port=ctrl bundle=control
#pragma HLS INTERFACE s_axilite port=y bundle=control
#pragma HLS INTERFACE s_axilite port=nx bundle=control
#pragma HLS INTERFACE s_axilite port=nw bundle=control
#pragma HLS INTERFACE s_axilite port=nb bundle=control
#pragma HLS INTERFACE s_axilite port=nc bundle=control
#pragma HLS INTERFACE s_axilite port=ny bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE axis port=sx
#pragma HLS INTERFACE axis port=sw
#pragma HLS INTERFACE axis port=sb
#pragma HLS INTERFACE axis port=sc
#pragma HLS INTERFACE axis port=sy
#pragma HLS DATAFLOW
  send128(x,nx,sx); send128(w,nw,sw); send128(buf,nb,sb);
  send64(ctrl,nc,sc); recv128(sy,y,ny);
}
