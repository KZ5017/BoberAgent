/* Test-only static descriptor formatter: no namespaces, candidate or exec.
 * Exercise the SAME production bounded parser and NUL argument writer. */
#define main native_main
#include "../../src/boberagent_execution_node/preparation/native/e5_confinement.c"
#undef main
int main(int argc,char **argv) {
    if (argc!=3) return 90;
    argument_fd=memfd_create("test-projection-arguments",MFD_ALLOW_SEALING);
    if (argument_fd<0) return 90;
    projection_records(argv[1],argv[2]);
    if (lseek(argument_fd,0,SEEK_SET)<0) return 90;
    char data[4096];ssize_t n;
    while ((n=read(argument_fd,data,sizeof(data)))>0)
        if (write_all(1,data,(size_t)n)) return 90;
    close(argument_fd);return n<0 ? 90 : 0;
}
