/*
** Copyright: 2020
** Author:    Dewey Garrett <dgarrett@panix.com>
**
** This program is free software; you can redistribute it and/or modify
** it under the terms of the GNU General Public License as published by
** the Free Software Foundation; either version 2 of the License, or
** (at your option) any later version.
**
** This program is distributed in the hope that it will be useful,
** but WITHOUT ANY WARRANTY; without even the implied warranty of
** MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
** GNU General Public License for more details.
**
** You should have received a copy of the GNU General Public License
** along with this program; if not, write to the Free Software
** Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
*/
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <limits.h>
#include <string.h>
#include "tooldata.hh"

#define DB_VERSION "v1.0"

//-----------------------------------------------------------------
/* pipe code adapted from:
** https://jineshkj.wordpress.com/2006/12/22/how-to-capture-stdin-stdout-and-stderr-of-child-program/
*/

 
#define NUM_PIPES          2
// pipes[0][] parent -------> child
// pipes[1][] parent <------- child
// pipes[][0] is for read
// pipes[][1] is for write
#define PARENT_WRITE_PIPE  0
#define PARENT_READ_PIPE   1
 
static int pipes[NUM_PIPES][2];
 
#define READ_FD  0
#define WRITE_FD 1
 
#define PARENT_READ_FD  ( pipes[PARENT_READ_PIPE] [READ_FD]  )
#define PARENT_WRITE_FD ( pipes[PARENT_WRITE_PIPE][WRITE_FD] )
 
#define CHILD_READ_FD   ( pipes[PARENT_WRITE_PIPE][READ_FD]  )
#define CHILD_WRITE_FD  ( pipes[PARENT_READ_PIPE] [WRITE_FD] )
 
static bool db_active=0;
static char db_childname[PATH_MAX];

static void handle_sigchild(int s)
{
    pid_t pid;
    int status;
    while((pid = waitpid(-1, &status, WUNTRACED | WCONTINUED | WNOHANG)) > 0) ;
    if (WIFSIGNALED(status))  {
        db_active = 0;
        fprintf(stderr,"%5d !!!%s terminated by signal %d\n"
               ,getpid(),db_childname,WTERMSIG(status));
    }
    if (WIFEXITED(status)) {
        db_active = 0;
        fprintf(stderr,"%5d ===%s normal exit status=%d\n"
               ,getpid(),db_childname,WEXITSTATUS(status));
    }
#if 0
    if (WIFSTOPPED(status)) {
        fprintf(stderr,"%5d ===%s stopped\n",getpid(),db_childname);
    }
    if (WIFCONTINUED(status)) {
        fprintf(stderr,"%5d ===%s continued\n",getpid(),db_childname);
    }
#endif
}

static int tooldata_fork_create(int myargc,char**myargv) 
{
    // O_DIRECT:packet mode
    if (pipe2(pipes[PARENT_READ_PIPE],O_DIRECT)) {
        perror("E: pipe2");exit(EXIT_FAILURE);
    }
    if (pipe2(pipes[PARENT_WRITE_PIPE],0)) {
        perror("E: pipe2");exit(EXIT_FAILURE);
    }
     
    signal(SIGCHLD, handle_sigchild);
    pid_t childpid = fork();
    if (childpid == -1) {
         perror("E: fork failed");
         exit(EXIT_FAILURE);
    }

    if(!childpid) { // CHILD------------------------------------
        dup2(CHILD_READ_FD,  STDIN_FILENO);
        dup2(CHILD_WRITE_FD, STDOUT_FILENO);
        close(CHILD_READ_FD);   // not reqd by child
        close(CHILD_WRITE_FD);  // not reqd by child
        close(PARENT_READ_FD);  // not reqd by child
        close(PARENT_WRITE_FD); // not reqd by child
        if (execv(myargv[0], myargv)) {perror("execv fail");}
        return -1;
    } else { // PARENT------------------------------------------
        close(CHILD_READ_FD); //not reqd by parent
        close(CHILD_WRITE_FD);//not reqd by parent
        db_active = 1;
        return 0;
    }
    return -1;
} // tooldata_fork_create()

static int tooldata_send_request(char request[],int howmany)
{
    // expect request with \n
    if (write(PARENT_WRITE_FD, request,howmany) < 0) {
        perror("tooldata_send_request write");
        return -1;
    }
    return 0;
} // tooldata_send_request()

static int tooldata_read_reply(char reply[],int len)
{
    char buffer[CANON_TOOL_ENTRY_LEN];
    int count = 0;
    buffer[count] = 0;
    if (!db_active) {
        fprintf(stderr,"tooldata_read_reply: db not active\n");
        return -1;
    }
    count = read(PARENT_READ_FD, buffer, sizeof(buffer)-1);
//dng ==0 ?? empty line would be count=1 \n
    if (count > 1) {
        buffer[count] = 0;
        // strip \n
        if (buffer[strlen(buffer)-1] =='\n') {
            buffer[strlen(buffer)-1] = 0;
        }
    } else {
        fprintf(stderr,"tooldata_read_reply IO Error count=%d\n",count);
        return -1;
    }
    snprintf(reply,len,"%s",buffer);

    return strlen(reply);
} // tooldata_read_reply()

int tooldata_db_init(char db_find_progname[],int random_toolchanger)
{
    int   child_argc = 2;
    char *child_argv[3];
    child_argv[0] = db_find_progname;
    child_argv[1] = (char*)DB_VERSION;
    child_argv[2] = 0;
    snprintf(db_childname,sizeof(db_childname),db_find_progname);

    fprintf(stderr,"%5d===tooldata_db_init\n",getpid());
    fprintf(stderr,"=====db_childname=%s\n",db_childname);
    //fprintf(stderr,"=====random_toolchanger=%d\n",random_toolchanger);
    if (0==tooldata_fork_create(child_argc,child_argv) ) {
        //fprintf(stderr,"=====db_init forked %s\n",child_argv[0]);
    } else {
        fprintf(stderr,"!!!!!db_init fork FAIL\n");
        perror("FORK");
        return -1;
    }

    // block for response
    char reply[CANON_TOOL_ENTRY_LEN];
    if (tooldata_read_reply(reply,sizeof(reply)) < 0) {
        fprintf(stderr,"!!!!!tooldata_read_reply initial read failed\n");
        return -1;
    } else {
        fprintf(stderr,"=====db startup reply=%s\n",reply);
    }
    return 0;
} // tooldata_db_init()

bool tooldata_db_active(void)
{
    return db_active;
} // tooldata_db_active()

int tooldata_db_find_index_for_tool(toolfind_t findmode,
                                    int random_toolchanger, int toolno)
{
    if (!db_active) {
        //this gets printed by axis gui on startup
        //fprintf(stderr,"%5d!!!db_find_index_for_tool: db not active %d\n"
        //       ,getpid(),toolno);
        return -1;
    }
    fprintf(stderr,"=====db_find_index tno=%d active=%d mode=%d random=%d\n"
           ,toolno,tooldata_db_active()
           ,(int)findmode
           ,random_toolchanger
           );

    char buffer[CANON_TOOL_ENTRY_LEN];
    snprintf(buffer,sizeof(buffer),"%d\n",toolno);
    if (tooldata_send_request(buffer,strlen(buffer))) {
        fprintf(stderr,"!!!!!tooldata_find_index_for_tool send fail\n");
        return -1;
    }

    char reply[CANON_TOOL_ENTRY_LEN];
    if (tooldata_read_reply(reply,sizeof(reply)) < 0) {
        fprintf(stderr,"%5d ??????replylen=%lu active=%d\n"
                ,getpid(),strlen(reply),db_active);
        return -1;
    }
    fprintf(stderr,"=====reply:%s\n",reply);

    // Note: comments not used with db_find
    // (the io process maintains comments from a tool table file)
    char **ttcomments = NULL;
    // bump index (+1) required for nonrandom_toolchanger:
    tooldata_add_init(tooldata_last_index_get()+1,
                      random_toolchanger,
                      TOOL_DB);

    int foundidx = tooldata_add_entry(reply,ttcomments);
    if (foundidx < 0) {
        fprintf(stderr,"!!!!!reply not parsed:\n");
        fprintf(stderr,"!!!!!%s\n",reply);
        return -1;
    }
CANON_TOOL_TABLE tt;
tooldata_get(&tt,foundidx);
fprintf(stderr,"after add_entry foundidx=%d tno=%d pno=%d z=%.3f\n"
,foundidx,tt.toolno,tt.pocketno,tt.offset.tran.z);

    return foundidx;
} // tooldata_db_find_index_for_tool()
