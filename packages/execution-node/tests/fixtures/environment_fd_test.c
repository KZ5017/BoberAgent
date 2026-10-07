/* Test-only caller of production FD narrowing. No cgroup/readiness claim. */
#define main production_main
#include "../../src/boberagent_execution_node/preparation/native/e5_confinement.c"
#undef main
#include <sys/socket.h>

static void assert_child_fds(int constructor) {
    struct stat s;
    for (int fd=3;fd<8192;fd++) {
        if (fstat(fd,&s)<0) continue;
        if (!constructor || fd!=3 || !S_ISREG(s.st_mode)
            || fcntl(fd,F_GETFD)!=0 || fcntl(fd,F_GET_SEALS)<0) _exit(98);
    }
    if (constructor && (fstat(3,&s) || write_all(3,"reviewed-export",15))) _exit(98);
}
int main(int argc,char **argv) {
    if (argc==2 && (!strcmp(argv[1],"child") || !strcmp(argv[1],"verify-child"))) {
        assert_child_fds(!strcmp(argv[1],"child")); return 0;
    }
    int real=argc==6 && !strcmp(argv[1],"bubblewrap");
    if (!real && argc!=2) return 99;
    int source=memfd_create("reviewed-environment-export",MFD_ALLOW_SEALING|MFD_CLOEXEC);
    if (source<0 || !(fcntl(source,F_GETFD)&FD_CLOEXEC)) return 99;
    /* Force both dup2 cases, plus an inheritable socket and very high host fd. */
    int same=!real && !strcmp(argv[1],"same");
    if (same) {
        if (dup2(source,3)<0 || fcntl(3,F_SETFD,FD_CLOEXEC)) return 99;
        if (source!=3) close(source);
        source=3;
    } else {
        int higher=fcntl(source,F_DUPFD_CLOEXEC,20);
        if (higher<0) return 99;
        close(source); source=higher;
    }
    int sockets[2];
    if (socketpair(AF_UNIX,SOCK_STREAM,0,sockets)<0
        || fcntl(sockets[0],F_DUPFD,4097)<0) return 99;
    int verify=!real && !strcmp(argv[1],"verify");
    pid_t child=fork();
    if (child<0) return 99;
    if (!child) {
        if (verify) close_extra(); else prepare_environment_export(source);
        if (!real) {
            char *args[]={argv[0],verify ? "verify-child" : "child",NULL};
            execv(argv[0],args); _exit(99);
        }
        /* Read-only test interpreter closure; only private namespace scratch.
         * This exercises the exact fixed constructor, NOT production C/D proof.
         * argv paths belong solely to this test fixture, never a capability.
         */
        const char *options[]={"--unshare-all","--die-with-parent","--new-session",
            "--ro-bind","/usr","/usr","--symlink","usr/lib","/lib",
            "--symlink","usr/lib64","/lib64","--proc","/proc",
            "--remount-ro","/proc","--dir","/trusted",
            "--ro-bind",argv[3],"/trusted/environment.py",
            "--ro-bind",argv[4],"/trusted/driver.py",
            "--tmpfs","/work","--chdir","/work","--clearenv",
            "--setenv","LANG","C",NULL};
        /* Match the sealed --args channel too: Bubblewrap must consume/close
         * this separate descriptor rather than leak it into the constructor. */
        argument_fd=memfd_create("fixed-test-options",MFD_ALLOW_SEALING);
        if (argument_fd<0) _exit(99);
        for (unsigned i=0;options[i];i++) projection_arg(options[i]);
        if (lseek(argument_fd,0,SEEK_SET)<0 || fcntl(argument_fd,F_ADD_SEALS,
            F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL)<0) _exit(99);
        char fd_number[16];snprintf(fd_number,sizeof(fd_number),"%d",argument_fd);
        char *args[]={argv[2],"--args",fd_number,"--","/usr/bin/python3.12",
            "-I","-S","-B","/trusted/driver.py",NULL};
        execv(argv[2],args); _exit(99);
    }
    int status;
    if (waitpid(child,&status,0)!=child || !WIFEXITED(status) || WEXITSTATUS(status)) return 98;
    if (verify) return 0;
    struct stat s;
    int seals=F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL;
    if (fstat(source,&s) || s.st_size<4 || (uint64_t)s.st_size>ENVIRONMENT_EXPORT_MAX
        || fcntl(source,F_ADD_SEALS,seals)<0 || lseek(source,0,SEEK_SET)<0) return 99;
    if (!real) return s.st_size==15 ? 0 : 99;
    int sink=open(argv[5],O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if (sink<0) return 99;
    char data[65536]; ssize_t n;
    while ((n=read(source,data,sizeof(data)))>0)
        if (write_all(sink,data,(size_t)n)) return 99;
    close(sink); return n<0 ? 99 : 0;
}
