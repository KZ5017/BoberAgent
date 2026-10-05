/* Test-only static formatter/launch capture: no namespaces, candidate or exec.
 * Exercise the SAME production parser, bounded writer, seals and fixed argv. */
#define execve captured_execve
#define main native_main
#include "../../src/boberagent_execution_node/preparation/native/e5_confinement.c"
#undef main
#undef execve
int captured_execve(const char *file,char *const argv[],char *const env[]) {
    (void)env;
    if (strcmp(file,argv[0]) || strcmp(argv[1],"--args")) _exit(91);
    int fd=(int)number(argv[2],0,1024);
    int seals=F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL;
    struct stat info;
    if (fcntl(fd,F_GET_SEALS)!=seals || fstat(fd,&info) || info.st_size>2*(long)MiB) _exit(91);
    /* Sealing must prevent all byte replacement, growth and truncation. */
    if (write(fd,"x",1)!=-1 || errno!=EPERM
        || ftruncate(fd,info.st_size+1)!=-1 || errno!=EPERM
        || ftruncate(fd,0)!=-1 || errno!=EPERM) _exit(91);
    for (unsigned i=0;argv[i];i++)
        if (write_all(1,argv[i],strlen(argv[i])+1)) _exit(91);
    if (write_all(1,"\0",1) || lseek(fd,0,SEEK_SET)<0) _exit(91);
    char data[4096];ssize_t n;
    while ((n=read(fd,data,sizeof(data)))>0)
        if (write_all(1,data,(size_t)n)) _exit(91);
    close(fd);_exit(n<0 ? 91 : 0);
}
int main(int argc,char **argv) {
    if (argc==6 && (!strcmp(argv[1],"--environment-create") || !strcmp(argv[1],"--environment-verify"))) {
        char *operation[15]={NULL};
        operation[5]=!strcmp(argv[1],"--environment-create") ? "python_environment_create" : "python_environment_verify";
        operation[10]=argv[2];operation[11]="/trusted/provider/environment.py";
        operation[12]=argv[5];operation[13]="3";operation[14]=argv[4];
        char *env[]={"PATH=/usr/bin:/bin","LANG=C",NULL};
        identity_launch(15,operation,"/trusted/bwrap-test","/trusted/helper-test",argv[3],env);
        return 91;
    }
    if (argc==2) {
        argument_fd=memfd_create("test-argument-bound",MFD_ALLOW_SEALING);
        if (argument_fd<0) return 90;
        char value[8193];memset(value,'x',sizeof(value));
        if (!strcmp(argv[1],"--count-limit"))
            for (unsigned i=0;i<=8500;i++) projection_arg("x");
        else if (!strcmp(argv[1],"--length-limit")) {
            value[8192]=0;projection_arg(value);
        } else if (!strcmp(argv[1],"--byte-limit")) {
            value[8191]=0;
            for (unsigned i=0;i<=256;i++) projection_arg(value);
        }
        return 91; /* Every tested bound must reject before returning. */
    }
    if (argc==4) {
        char *operation[12]={NULL};
        operation[5]="python_identity";
        operation[10]=argv[1];operation[11]=argv[3];
        char *env[]={"PATH=/usr/bin:/bin","LANG=C",NULL};
        identity_launch(12,operation,"/trusted/bwrap-test","/trusted/helper-test",argv[2],env);
        return 91;
    }
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
