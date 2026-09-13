#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>
#ifndef TEST_N
#error TEST_N must be set
#endif
#if TEST_KIND == 1
extern "C" void kernel_getrf_0(double*, int*);
#elif TEST_KIND == 2
extern "C" void kernel_getrf_nopivot_0(double*);
#elif TEST_KIND == 3
extern "C" void kernel_gematrixinverse_0(int, double*);
#elif TEST_KIND == 4
extern "C" void kernel_geqrf_0(double*, double*);
#endif
int main() {
    const int n=TEST_N;
    std::vector<double> a(n*n), original(n*n), tau(n);
    std::vector<int> perm(n);
    for(int i=0;i<n;i++) for(int j=0;j<n;j++)
        a[i*n+j]=(i==j ? n*0.04+4.0 : 0.01*((i*17+j*13)%11-5));
#if TEST_KIND == 1
    // Force nontrivial pivoting while preserving invertibility.
    for(int j=0;j<n;j++) std::swap(a[j],a[(n-1)*n+j]);
#endif
    original=a;
#if TEST_KIND == 1
    kernel_getrf_0(a.data(),perm.data());
#elif TEST_KIND == 2
    kernel_getrf_nopivot_0(a.data());
    for(int i=0;i<n;i++) perm[i]=i;
#elif TEST_KIND == 3
    kernel_gematrixinverse_0(n,a.data());
#elif TEST_KIND == 4
    kernel_geqrf_0(a.data(),tau.data());
#endif
    for(double x:a) if(!std::isfinite(x)) return 2;
#if TEST_KIND == 1
    std::vector<int> seen(n,0);
    for(int x:perm) if(x<0 || x>=n || ++seen[x]!=1) return 3;
#endif
    double worst=0;
    // Check every diagonal and 128 deterministic off-diagonal entries.
    for(int t=0;t<n+128;t++) {
        int i=t<n ? t : ((t-n)*37+3)%n;
        int j=t<n ? t : ((t-n)*53+7)%n;
        double actual=0,expected=0;
#if TEST_KIND == 1 || TEST_KIND == 2
        for(int k=0;k<=std::min(i,j);k++) actual+=(k==i?1.0:a[i*n+k])*a[k*n+j];
        expected=original[perm[i]*n+j];
#elif TEST_KIND == 3
        for(int k=0;k<n;k++) actual+=original[i*n+k]*a[k*n+j];
        expected=i==j?1.0:0.0;
#elif TEST_KIND == 4
        for(int k=0;k<n;k++) expected+=original[k*n+i]*original[k*n+j];
        for(int k=0;k<=std::min(i,j);k++) actual+=a[k*n+i]*a[k*n+j];
#endif
        double error=std::fabs(actual-expected)/std::max(1.0,std::fabs(expected));
        worst=std::max(worst,error);
    }
    std::printf("NUMERICAL_SAMPLE N=%d KIND=%d ENTRIES=%d WORST_RELATIVE=%.17g\n",n,TEST_KIND,n+128,worst);
    if(worst>1e-7) {std::puts("NUMERICAL_SAMPLE_FAIL");return 1;}
    std::puts("NUMERICAL_SAMPLE_PASS");
    return 0;
}
