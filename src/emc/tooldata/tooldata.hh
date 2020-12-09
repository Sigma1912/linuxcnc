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
#ifndef TOOL_DATA_H
#define TOOL_DATA_H

#include "canon.hh"
#include "emc_nml.hh"

#ifdef CPLUSPLUS
extern"C" {
#endif

typedef enum {
    IDX_OK = 0,
    IDX_UNUSED,
    IDX_INVALID,
} toolidx_t;

typedef enum {
    DB_NOTUSED=0,  // equivalent to not specifying in inifile
    DB_LAST,
    DB_FIRST,
    DB_ONLY,
} toolfind_t;
//----------------------------------------------------------
// tooldata_*(): access to internal tool table data:
struct    CANON_TOOL_TABLE tooldata_entry_init(void);
int                        tooldata_put(struct CANON_TOOL_TABLE tdata,int idx);
toolidx_t tooldata_get(CANON_TOOL_TABLE* pdata,int idx);

void   tooldata_last_index_set(int idx);
int    tooldata_last_index_get(void);
int    tooldata_find_index_for_tool(int toolno);

void   tooldata_add_init(int nonrandom_start_idx,
                         bool random_toolchanger,
                         tool_source_t tool_from);
int    tooldata_add_entry(const char *input_line,char *ttcomments[]);

void tooldata_save_line(FILE* fp,
                        int idx,
                        int random_toolchanger,
                        char *ttcomments[]);

int loadToolTable(const char *filename,
#ifdef TOOL_MMAP //{
       // toolTable[] parm not used for mmap
#else //}{
       struct CANON_TOOL_TABLE toolTable[CANON_POCKETS_MAX],
#endif //}
       char *ttcomments[CANON_POCKETS_MAX],
       int random_toolchanger
);

int saveToolTable(const char *filename,
#ifdef TOOL_MMAP //{
    // toolTable[] param not used for mmap
#else //}{
        CANON_TOOL_TABLE toolTable[],
#endif //}
        char *ttcomments[CANON_POCKETS_MAX],
        int random_toolchanger);


//----------------------------------------------------------
//mmap specific
int  tool_mmap_creator(EMC_TOOL_STAT const  *ptr,int random_toolchanger);
int  tool_mmap_user(void);
void tool_mmap_close(void);

//----------------------------------------------------------
//nml specific
int tool_nml_register(CANON_TOOL_TABLE *tblptr,int* last_idx_ptr);

//----------------------------------------------------------
// db_find

int   tooldata_db_init(char db_find_progname[],int random_toolchanger);
bool  tooldata_db_active(void);
int   tooldata_db_find_index_for_tool(toolfind_t findmode,
                                      int random_toolchanger,
                                      int toolno);
#ifdef CPLUSPLUS
}
#endif
#endif
